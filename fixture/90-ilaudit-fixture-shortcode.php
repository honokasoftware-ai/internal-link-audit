<?php
/**
 * Fixture only. Never shipped with the plugin.
 *
 * Registers a shortcode that prints a link and an image. The post that uses it has
 * neither in its stored post_content, so the measurement can only see them if the
 * plugin really runs the_content filters. That is check V9 in tools/harness.py.
 *
 * @package internal-link-audit-fixture
 */

add_shortcode(
	'fixture_link',
	static function () {
		return '<p><a href="/delta/">see delta</a></p><p><img src="/wp-content/uploads/shortcode.png"></p>';
	}
);
