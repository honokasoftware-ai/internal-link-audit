=== Internal Link Audit ===
Contributors: honokasoftware
Tags: internal links, orphaned posts, image alt, accessibility, audit
Requires at least: 6.0
Tested up to: 7.1
Requires PHP: 7.4
Stable tag: 1.0.1
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Finds posts no other post links to, images with no alt text, and internal links per post. Read only: it never changes your content.

== Description ==

Three things about a blog are invisible while you work on one post at a time:

1. **Posts that no other post links to.** A post can be published, indexed and perfectly good, and still sit on its own with nothing pointing at it from inside your own site.
2. **Images with no alt attribute.** Not `alt=""`, which is the correct markup for a decorative image, but images with no alt attribute at all.
3. **How many internal links each post has**, and which posts have none going out.

This plugin reads your published posts and puts those three numbers on one screen under **Tools -> Internal Link Audit**, with the list of which posts they are.

**It is read only.** It never edits, inserts or deletes a post, a page, an option set by anything else, or a file. There is nothing to undo.

= What it does not do =

It does not write links for you, suggest keywords, promise a ranking, check links to other sites for breakage, or score your post. It reports what is there. Deciding what to link is still your job.

= How the numbers are counted =

* Only published posts are read. Pages, drafts, attachments and other post types are left out.
* Blocks and shortcodes inside a post are expanded before it is measured, so a link written inside one still counts. Markup that another plugin appends to every post when it is displayed, such as a related posts box, share buttons or an advert, is not counted: it belongs to the site rather than to the post. Text inside HTML comments is not counted either, because it is not on the page.
* An internal link is a link to this same site. Links starting with `tel:`, `mailto:` or `#` are not internal links. A link from a post to itself does not count as a link to it.
* `alt=""` is not reported as missing. Only an `img` tag with no alt attribute at all is.
* Link targets are resolved with WordPress' own `url_to_postid()`, so a link written before a slug or category change still counts for the post it now points to. An outside crawler comparing URL paths cannot do this.

= Privacy =

The plugin makes no HTTP request of any kind. It contains no call to `wp_remote_get`, `wp_remote_post`, `curl_init` or `fsockopen`, so there is no analytics, no phone home and no licence check. Nothing about your site leaves your server. The report is stored in a single option, `ilaudit_state`, and the screen has a button that deletes it. Deleting the plugin deletes it too.

= Everything is free =

There is no paid tier, no trial, no locked feature and no upsell. This is the whole plugin.

== Installation ==

1. Install through **Plugins -> Add New**, or upload the folder to `wp-content/plugins/`.
2. Activate it.
3. Open **Tools -> Internal Link Audit** and press **Run the scan**.

The scan reads 100 posts per request and continues when you press the button again, so it does not have to finish inside one page load.

== Frequently Asked Questions ==

= Does it change my posts? =

No. It only reads. There is no write path in the plugin for post content.

= How many posts can it handle? =

5,000 published posts. Above that the oldest 5,000 are read and the screen says so, rather than reporting a short list as if it were complete.

= Why does a post with no links out still count as linked to? =

Those are two different numbers and the screen shows both. "Posts no other post links to" is about links coming in. "Posts with no internal link out" is about links going out. A post can be either, both or neither.

= Who can see the report? =

Only users who can manage options, which normally means administrators. The screen refuses anyone else.

= It says an image has no alt, but I set one =

Check whether it is `alt=""`. That is correct markup for a decorative image and this plugin does not report it as missing. Note that the measurement reads the post's own content with blocks and shortcodes expanded, so an alt attribute that your theme or another plugin adds at display time is not seen here.

= I have a related posts plugin. Does its box count as internal links? =

No. Markup that a plugin or a theme appends to every post when it is displayed is not part of that post and is not counted, in either direction. Without that rule a related posts box would add a link to every post on the site and no post would ever look orphaned again.

== Screenshots ==

1. Tools -> Internal Link Audit after a scan: the summary of six figures and the list of posts nothing links to.

== Changelog ==

= 1.0.1 =
* Fixed: content that another plugin appends through the `the_content` filter, such as a related posts box, was counted as part of the post. On a site with such a plugin every figure was too high and an orphaned post could look as though something linked to it.
* Changed: the query that lists published posts no longer suppresses query filters.

= 1.0.0 =
* First release.
