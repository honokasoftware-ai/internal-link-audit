<?php
/**
 * Plugin Name:       Internal Link Audit
 * Plugin URI:        https://github.com/honokasoftware-ai/internal-link-audit
 * Description:       Read-only report of three things you cannot see one post at a time: published posts that no other post links to, images with no alt text, and how many internal links each post has. It never changes your content.
 * Version:           1.0.0
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * Author:            Honoka Software
 * License:           GPL-2.0-or-later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       internal-link-audit
 *
 * Internal Link Audit is free software: you can redistribute it and/or modify it under
 * the terms of the GNU General Public License as published by the Free Software
 * Foundation, either version 2 of the License, or (at your option) any later version.
 *
 * Design rules this file keeps on purpose (WordPress.org guidelines 5 / 7 / 10 / 11):
 *   - Nothing is locked behind a payment and there is no trial period (guideline 5).
 *   - No HTTP request leaves the site. There is no analytics, no phone-home, no
 *     licence check. The whole report is computed from the local database (guideline 7).
 *   - No hook touches the front end. No credit, badge or link is printed on the
 *     public site (guideline 10).
 *   - No admin notice, banner or nag is registered. Output happens only on this
 *     plugin's own screen, which the user has to open (guideline 11).
 * tools/harness.py asserts each of those four by reading this file (checks V15 to V19).
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'ILAUDIT_VERSION', '1.0.0' );
define( 'ILAUDIT_STATE', 'ilaudit_state' );   // scan in progress / finished state
define( 'ILAUDIT_SLUG', 'internal-link-audit' );
define( 'ILAUDIT_MAX_POSTS', 5000 );          // hard ceiling, see readme.txt FAQ
define( 'ILAUDIT_BATCH', 100 );               // posts handled per request

/**
 * Register the one admin screen. Tools -> Internal Link Audit.
 */
function ilaudit_menu() {
	add_management_page(
		__( 'Internal Link Audit', 'internal-link-audit' ),
		__( 'Internal Link Audit', 'internal-link-audit' ),
		'manage_options',
		ILAUDIT_SLUG,
		'ilaudit_render'
	);
}
add_action( 'admin_menu', 'ilaudit_menu' );

/**
 * Remove our stored report when the plugin is deleted.
 */
function ilaudit_uninstall() {
	delete_option( ILAUDIT_STATE );
}

/* ------------------------------------------------------------------ *
 * Measurement
 * ------------------------------------------------------------------ */

/**
 * Pull every href out of a block of HTML.
 *
 * Why not just one quoting style: href can be written with double quotes, single
 * quotes or no quotes at all, and a tool that reads only double quotes silently
 * drops whole sites. Measured on 2026-10-03 on www.my-painter.com, where reading
 * only double quotes lost four single-quoted internal links. The value must not
 * start with a backslash so that href=\"...\" inside a JSON-LD <script> block is
 * not mistaken for a link (measured on kousei-tokyo-hachioji.com the same day).
 * Only an ASCII space may follow "<a": "<a\xe3\x80\x80href=..." with an ideographic
 * space is not a link in a browser, so it is not one here either.
 *
 * @param string $html HTML to read.
 * @return string[] Raw href values, HTML-entity decoded.
 */
function ilaudit_hrefs( $html ) {
	$out = array();
	if ( ! preg_match_all(
		'/<a[ \t\r\n\f][^>]*?\bhref\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'>\\\\][^\s"\'>]*))/i',
		$html,
		$m,
		PREG_SET_ORDER
	) ) {
		return $out;
	}
	foreach ( $m as $one ) {
		$raw = '';
		for ( $i = 1; $i <= 3; $i++ ) {
			if ( isset( $one[ $i ] ) && '' !== $one[ $i ] ) {
				$raw = $one[ $i ];
				break;
			}
		}
		$out[] = html_entity_decode( $raw, ENT_QUOTES | ENT_HTML5, 'UTF-8' );
	}
	return $out;
}

/**
 * Count <img> tags, and how many of them have no usable alt attribute.
 *
 * An alt that is present but empty (alt="") is the correct markup for a purely
 * decorative image, so it is NOT reported as missing. Only a missing attribute is.
 *
 * @param string $html HTML to read.
 * @return array{imgs:int,no_alt:int}
 */
function ilaudit_images( $html ) {
	$imgs   = array();
	$no_alt = 0;
	if ( preg_match_all( '/<img\b[^>]*>/i', $html, $m ) ) {
		$imgs = $m[0];
		foreach ( $imgs as $tag ) {
			if ( ! preg_match( '/\balt\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s"\'>][^\s>]*)/i', $tag ) ) {
				$no_alt++;
			}
		}
	}
	return array(
		'imgs'   => count( $imgs ),
		'no_alt' => $no_alt,
	);
}

/**
 * Is this href a link to somewhere on this same site?
 *
 * tel:, mailto:, javascript: and bare "#anchor" links are not internal links.
 * Counting tel: as an internal link once moved a reported median from 3 to 4
 * (2026-09-29), which is a wrong number handed to a paying reader.
 *
 * @param string $href Raw href value.
 * @return string|false Absolute URL on this site, or false.
 */
function ilaudit_same_site( $href ) {
	$raw = trim( $href );
	if ( '' === $raw || '#' === $raw[0] ) {
		return false;
	}
	$scheme = strtolower( (string) wp_parse_url( $raw, PHP_URL_SCHEME ) );
	if ( '' !== $scheme && 'http' !== $scheme && 'https' !== $scheme ) {
		return false;
	}
	$abs  = $raw;
	$host = (string) wp_parse_url( $raw, PHP_URL_HOST );
	if ( '' === $host ) {
		if ( '' !== $scheme ) {
			// "http:info@example.com" has a scheme but no host. A browser leaves
			// this site; resolving it against home_url() would wrongly make it
			// internal (seen on wark-lasercutter.com, 2026-10-03).
			return false;
		}
		if ( '' === $raw || '/' !== $raw[0] ) {
			return false; // relative path; too ambiguous to attribute, so not counted
		}
		$abs = home_url( $raw );
	} else {
		$mine = (string) wp_parse_url( home_url(), PHP_URL_HOST );
		$bare = static function ( $h ) {
			$h = strtolower( $h );
			return 0 === strpos( $h, 'www.' ) ? substr( $h, 4 ) : $h;
		};
		if ( $bare( $host ) !== $bare( $mine ) ) {
			return false;
		}
	}
	return $abs;
}

/**
 * Resolve a same-site URL to a post ID, using WordPress' own resolver.
 *
 * This is the one place where a plugin can be more accurate than an outside
 * crawler: url_to_postid() understands this site's permalink structure, so a
 * link written before a category rename still resolves to the right post.
 * Guessing from the path alone over-counted orphans by 8 on www.my-painter.com.
 *
 * @param string $url Absolute URL on this site.
 * @return int Post ID, or 0.
 */
function ilaudit_resolve( $url ) {
	static $cache = array();
	if ( ! isset( $cache[ $url ] ) ) {
		$cache[ $url ] = (int) url_to_postid( $url );
	}
	return $cache[ $url ];
}

/**
 * Measure one post exactly as a visitor sees it.
 *
 * the_content filters are applied so that shortcodes and blocks are expanded;
 * counting raw post_content would miss links and images that the theme builds.
 * HTML comments are dropped first: a commented-out draft is not on the page, so
 * reporting its images as "missing alt" would be false (measured on nendeb.com).
 *
 * @param WP_Post $post Post to measure.
 * @return array
 */
function ilaudit_measure_post( $post ) {
	$html = (string) apply_filters( 'the_content', $post->post_content );
	$html = preg_replace( '/<!--.*?(?:-->|$)/s', '', $html );

	$img      = ilaudit_images( $html );
	$internal = 0;
	$targets  = array();
	foreach ( ilaudit_hrefs( $html ) as $href ) {
		$abs = ilaudit_same_site( $href );
		if ( false === $abs ) {
			continue;
		}
		$internal++;
		$id = ilaudit_resolve( $abs );
		if ( $id && $id !== (int) $post->ID ) { // a self-link does not rescue a post
			$targets[ $id ] = true;
		}
	}
	return array(
		'internal' => $internal,
		'imgs'     => $img['imgs'],
		'no_alt'   => $img['no_alt'],
		'targets'  => array_keys( $targets ),
	);
}

/* ------------------------------------------------------------------ *
 * Scan state
 * ------------------------------------------------------------------ */

/**
 * Fresh, empty scan state.
 *
 * @return array
 */
function ilaudit_blank_state() {
	return array(
		'version'  => ILAUDIT_VERSION,
		'ids'      => array(),   // every published post id, in a fixed order
		'done'     => 0,         // how many of ids have been measured
		'per'      => array(),   // id => internal / imgs / no_alt
		'inbound'  => array(),   // id => number of OTHER posts linking to it
		'capped'   => false,     // true when the site has more posts than the ceiling
		'started'  => 0,
		'finished' => 0,
	);
}

/**
 * Read stored state, or a blank one.
 *
 * @return array
 */
function ilaudit_state() {
	$s = get_option( ILAUDIT_STATE );
	if ( ! is_array( $s ) || ! isset( $s['ids'] ) ) {
		return ilaudit_blank_state();
	}
	return array_merge( ilaudit_blank_state(), $s );
}

/**
 * Begin a scan: take the list of published post ids and store it.
 *
 * @return array New state.
 */
function ilaudit_start() {
	$ids = get_posts(
		array(
			'post_type'        => 'post',
			'post_status'      => 'publish',
			'numberposts'      => ILAUDIT_MAX_POSTS + 1,
			'fields'           => 'ids',
			'orderby'          => 'ID',
			'order'            => 'ASC',
			'suppress_filters' => true,
		)
	);
	$state = ilaudit_blank_state();
	if ( count( $ids ) > ILAUDIT_MAX_POSTS ) {
		$state['capped'] = true;
		$ids             = array_slice( $ids, 0, ILAUDIT_MAX_POSTS );
	}
	$state['ids']     = array_map( 'intval', $ids );
	$state['started'] = time();
	update_option( ILAUDIT_STATE, $state, false );
	return $state;
}

/**
 * Measure the next batch of posts and store the result.
 *
 * Done in batches so that a site with thousands of posts does not hit the PHP
 * time limit. Each request picks up where the last one stopped.
 *
 * @return array State after this batch.
 */
function ilaudit_step() {
	$state = ilaudit_state();
	$slice = array_slice( $state['ids'], $state['done'], ILAUDIT_BATCH );
	foreach ( $slice as $id ) {
		$post = get_post( $id );
		$state['done']++;
		if ( ! $post ) {
			continue; // deleted while the scan was running
		}
		$m                       = ilaudit_measure_post( $post );
		$state['per'][ (string) $id ] = array(
			'internal' => $m['internal'],
			'imgs'     => $m['imgs'],
			'no_alt'   => $m['no_alt'],
		);
		foreach ( $m['targets'] as $t ) {
			$k                        = (string) $t;
			$state['inbound'][ $k ]   = isset( $state['inbound'][ $k ] ) ? $state['inbound'][ $k ] + 1 : 1;
		}
	}
	if ( $state['done'] >= count( $state['ids'] ) ) {
		$state['finished'] = time();
	}
	update_option( ILAUDIT_STATE, $state, false );
	return $state;
}

/**
 * Turn a finished scan into the numbers the screen shows.
 *
 * Orphans are only meaningful once every post has been read, because the post
 * that links to post #1 may be the last one in the list. While a scan is still
 * running the screen says so instead of showing a number that will change.
 *
 * @param array $state Scan state.
 * @return array
 */
function ilaudit_summary( $state ) {
	$ids      = $state['ids'];
	$orphans  = array();
	$internal = array();
	$no_alt   = 0;
	$imgs     = 0;
	foreach ( $ids as $id ) {
		$k = (string) $id;
		if ( ! isset( $state['per'][ $k ] ) ) {
			continue;
		}
		$row        = $state['per'][ $k ];
		$internal[] = (int) $row['internal'];
		$no_alt    += (int) $row['no_alt'];
		$imgs      += (int) $row['imgs'];
		if ( empty( $state['inbound'][ $k ] ) ) {
			$orphans[] = $id;
		}
	}
	sort( $internal );
	$n      = count( $internal );
	$median = 0.0;
	if ( $n > 0 ) {
		$median = ( 0 === $n % 2 )
			? ( $internal[ $n / 2 - 1 ] + $internal[ $n / 2 ] ) / 2
			: (float) $internal[ ( $n - 1 ) / 2 ];
	}
	return array(
		'posts'         => $n,
		'orphans'       => $orphans,
		'orphan_count'  => count( $orphans ),
		'images'        => $imgs,
		'images_no_alt' => $no_alt,
		'internal_sum'  => array_sum( $internal ),
		'internal_med'  => $median,
		'zero_internal' => count( array_filter( $internal, static function ( $v ) { return 0 === $v; } ) ),
		'complete'      => ( $n > 0 && $state['done'] >= count( $ids ) ),
	);
}

/* ------------------------------------------------------------------ *
 * The one screen
 * ------------------------------------------------------------------ */

/**
 * Handle the button presses, then draw the screen.
 */
function ilaudit_render() {
	if ( ! current_user_can( 'manage_options' ) ) {
		wp_die( esc_html__( 'You do not have permission to view this report.', 'internal-link-audit' ) );
	}
	$action = isset( $_POST['ilaudit_action'] ) ? sanitize_key( wp_unslash( $_POST['ilaudit_action'] ) ) : '';
	if ( '' !== $action ) {
		check_admin_referer( 'ilaudit_scan' );
		if ( 'start' === $action ) {
			ilaudit_start();
			ilaudit_step();
		} elseif ( 'continue' === $action ) {
			ilaudit_step();
		} elseif ( 'forget' === $action ) {
			delete_option( ILAUDIT_STATE );
		}
	}
	$state   = ilaudit_state();
	$summary = ilaudit_summary( $state );
	$total   = count( $state['ids'] );
	$running = ( $total > 0 && $state['done'] < $total );

	echo '<div class="wrap">';
	echo '<h1>' . esc_html__( 'Internal Link Audit', 'internal-link-audit' ) . '</h1>';
	echo '<p>' . esc_html__( 'This report only reads your posts. It never edits, inserts or deletes anything, and it sends nothing anywhere.', 'internal-link-audit' ) . '</p>';

	echo '<form method="post">';
	wp_nonce_field( 'ilaudit_scan' );
	if ( $running ) {
		printf(
			'<p><strong>%s</strong></p>',
			esc_html(
				sprintf(
					/* translators: 1: posts measured, 2: posts found */
					__( 'Scan in progress: %1$d of %2$d posts measured.', 'internal-link-audit' ),
					(int) $state['done'],
					$total
				)
			)
		);
		submit_button( __( 'Measure the next batch', 'internal-link-audit' ), 'primary', 'ilaudit_go', false );
		echo ' <input type="hidden" name="ilaudit_action" value="continue" />';
	} else {
		submit_button(
			0 === $total ? __( 'Run the scan', 'internal-link-audit' ) : __( 'Run the scan again', 'internal-link-audit' ),
			'primary',
			'ilaudit_go',
			false
		);
		echo ' <input type="hidden" name="ilaudit_action" value="start" />';
	}
	echo '</form>';

	if ( 0 === $total ) {
		echo '<p>' . esc_html__( 'No scan has been run yet.', 'internal-link-audit' ) . '</p></div>';
		return;
	}

	if ( $state['capped'] ) {
		echo '<p><em>' . esc_html(
			sprintf(
				/* translators: 1: ceiling on the number of posts, 2: the same ceiling */
				__( 'This site has more than %1$d published posts. Only the oldest %2$d were read, so the orphan list is incomplete.', 'internal-link-audit' ),
				ILAUDIT_MAX_POSTS,
				ILAUDIT_MAX_POSTS
			)
		) . '</em></p>';
	}

	echo '<h2>' . esc_html__( 'Summary', 'internal-link-audit' ) . '</h2><table class="widefat striped" style="max-width:40em"><tbody>';
	$rows = array(
		array( __( 'Published posts read', 'internal-link-audit' ), number_format_i18n( $summary['posts'] ) ),
		array(
			__( 'Posts no other post links to', 'internal-link-audit' ),
			$summary['complete']
				? number_format_i18n( $summary['orphan_count'] )
				: __( 'available when the scan finishes', 'internal-link-audit' ),
		),
		array( __( 'Images with no alt attribute', 'internal-link-audit' ), number_format_i18n( $summary['images_no_alt'] ) . ' / ' . number_format_i18n( $summary['images'] ) ),
		array( __( 'Internal links found', 'internal-link-audit' ), number_format_i18n( $summary['internal_sum'] ) ),
		array( __( 'Internal links per post (median)', 'internal-link-audit' ), number_format_i18n( $summary['internal_med'], 1 ) ),
		array( __( 'Posts with no internal link out', 'internal-link-audit' ), number_format_i18n( $summary['zero_internal'] ) ),
	);
	foreach ( $rows as $r ) {
		echo '<tr><td>' . esc_html( $r[0] ) . '</td><td><strong>' . esc_html( $r[1] ) . '</strong></td></tr>';
	}
	echo '</tbody></table>';

	if ( $summary['complete'] ) {
		echo '<h2>' . esc_html__( 'Posts no other post links to', 'internal-link-audit' ) . '</h2>';
		if ( 0 === $summary['orphan_count'] ) {
			echo '<p>' . esc_html__( 'Every post is linked to from at least one other post.', 'internal-link-audit' ) . '</p>';
		} else {
			echo '<table class="widefat striped"><thead><tr>';
			echo '<th>' . esc_html__( 'Post', 'internal-link-audit' ) . '</th>';
			echo '<th>' . esc_html__( 'Published', 'internal-link-audit' ) . '</th>';
			echo '<th>' . esc_html__( 'Internal links out', 'internal-link-audit' ) . '</th>';
			echo '<th>' . esc_html__( 'Images with no alt', 'internal-link-audit' ) . '</th>';
			echo '</tr></thead><tbody>';
			foreach ( $summary['orphans'] as $id ) {
				$row = $state['per'][ (string) $id ];
				printf(
					'<tr><td><a href="%1$s">%2$s</a></td><td>%3$s</td><td>%4$s</td><td>%5$s</td></tr>',
					esc_url( (string) get_edit_post_link( $id ) ),
					esc_html( get_the_title( $id ) ),
					esc_html( (string) get_the_date( 'Y-m-d', $id ) ),
					esc_html( number_format_i18n( (int) $row['internal'] ) ),
					esc_html( number_format_i18n( (int) $row['no_alt'] ) )
				);
			}
			echo '</tbody></table>';
		}
	}

	echo '<h2>' . esc_html__( 'How these numbers are counted', 'internal-link-audit' ) . '</h2><ul>';
	$notes = array(
		__( 'Only published posts are read. Pages, drafts, attachments and other post types are left out.', 'internal-link-audit' ),
		__( 'Each post is measured after the content filters run, so shortcodes and blocks are counted the way a visitor sees them. Text inside HTML comments is not counted, because it is not on the page.', 'internal-link-audit' ),
		__( 'An internal link is a link to this same site. Links starting with tel:, mailto: or # are not internal links. A link from a post to itself does not count as a link to it.', 'internal-link-audit' ),
		__( 'alt="" is correct markup for a decorative image and is not reported as missing. Only an img tag with no alt attribute at all is.', 'internal-link-audit' ),
		__( 'Link targets are resolved with WordPress\' own url_to_postid(), so a link written before a slug or category change still counts for the post it now points to.', 'internal-link-audit' ),
	);
	foreach ( $notes as $note ) {
		echo '<li>' . esc_html( $note ) . '</li>';
	}
	echo '</ul>';

	echo '<form method="post">';
	wp_nonce_field( 'ilaudit_scan' );
	echo '<input type="hidden" name="ilaudit_action" value="forget" />';
	submit_button( __( 'Delete the stored report', 'internal-link-audit' ), 'delete', 'ilaudit_forget', false );
	echo '</form>';
	echo '</div>';
}
