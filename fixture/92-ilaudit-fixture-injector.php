<?php
/**
 * Plugin Name: Internal Link Audit fixture: a plugin that appends to the_content
 *
 * Part of the fixture, not part of the product. It stands in for the single most
 * common thing a third party plugin does on a real WordPress site: hook
 * the_content and append its own markup to every post. A related posts box, a
 * share bar and an injected advert all have this shape.
 *
 * The class name deliberately carries no part of the plugin's own name, because
 * check V15 asserts the public pages carry no mark from the plugin and would
 * otherwise be measuring this fixture file instead.
 *
 * Nothing it prints is stored in any post. So every figure the harness checks
 * must come out the same with this file present as without it, and the post it
 * links to (Eta) must stay in the orphan list. Checks V25 and V26 measure both
 * halves: that the markup really is on the page, and that the report ignores it.
 */
add_filter(
	'the_content',
	function ( $content ) {
		return $content
			. '<div class="fixture-related-posts">'
			. '<p>You may also like: <a href="/eta/">Eta</a></p>'
			. '<img src="/wp-content/uploads/related-thumb.png">'
			. '</div>';
	},
	20
);
