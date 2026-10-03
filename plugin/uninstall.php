<?php
/**
 * Runs when the user deletes the plugin. Removes the one option we store.
 *
 * @package internal-link-audit
 */

if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
	exit;
}

delete_option( 'ilaudit_state' );
