=========
Changelog
=========

---------------
Changelog 1.0.0
---------------

Initial public release.

* Utility to add @mention'ed users in comments to the watchers list for an issue
* Simple utilities to build up gerrit -> jira integration, including persistent
  state and incremental updates
* Utility to generate release notes for gerrit changes merged or jira issues
  closed in a release
* Utility to set the "Fix Version" for all issues that were closed between two
  releases.

1.0.1
=====

* Fix wrapper script argv passing
* Fix dependency on wrong enum package

1.0.2
=====

* Add missing dependency on jira

1.0.3
=====

* Rename release-notes to changes-in-release and add a release-notes which
  combines changes-in-release and issues-in-release
