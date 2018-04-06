==============
Workflow Tools
==============

Some tools for automating gerrit, jira, etc.

When my work team moved our issue tracking to JIRA, it was a boon for project
management, but introduced some significant development friction. Jira is
powerful, but it is not fast. It takes about 12 clicks to accomplish anything
and it seems that every UI interaction involves some massive database update.

``flow-tools`` started as a couple of scripts to automate common time-consuming
interactions with JIRA. This has come to include a couple of Gerrit -> JIRA
integrations as well.


-----
Usage
-----

::

    usage: flow-tools [-h] [-c CONFIG] [-v] <command> ...

    Command line client to automate parts of our agile workflow.

    positional arguments:
      <command>
        close-issues-merged
                            Walk the list of merges on master for the given user.
                            Look for tags in the commit message indicating that
                            the commit closes/resolves an issue. Then login to
                            jira and close those issues if they are not already
                            closed.
        set-issues-fixed-in-release
                            For each issue closed in a release, set the "Fixed
                            Release" field of jira
        add-mentions-to-watchers
                            Get a list of all mentioned users in the issue
                            comments and description, and add any to the watcher
                            list that are not already watchers.
        print-releases      Parse tags on the gerrit remote and print a sorted
                            list of version strings, using the pattern and sort
                            functions from the config file.
        release-notes       Show a list of commit message summaries for each
                            commit in the series between one version and another.
        issues-in-release   Show a list of issues that were closed in a release.
                            In particular, lookup all commits that went into a
                            release (since the common ancestor with the previous
                            release). For each commit, get the list of issues
                            closed or resolved through commit message meta data.
                            These are the issues considered "in" the release.
        increment-jira-from-gerrit
                            Monitor changes on gerrit for tags indicating
                            associated issues that are resolved by those changes.
                            As a change moves through the gerrit workflow, move
                            the associated issue through the jira workflow. Same
                            as update-jira-from-gerrit but in this case the start
                            of the period to search will the last successful time
                            we ran this command, and the end time will be right
                            now.
        update-jira-from-gerrit
                            Monitor changes on gerrit for tags indicating
                            associated issues that are resolved by those changes.
                            As a change moves through the gerrit workflow, move
                            the associated issue through the jira workflow.

    optional arguments:
      -h, --help            show this help message and exit
      -c CONFIG, --config CONFIG
      -v, --version         show program's version number and exit

    Subcommands have their own options. Use <command> -h or <command> --help to
    see specific help for each subcommand.


--------
Examples
--------

Move at-mentions to watchers
============================

Find all the users who are `@`-mentioned in comments on the ticket `PROJ-1234`
and make them watchers of that ticket::

    flow-tools add-mentions-to-watchers PROJ-1234

Simple Gerrit/Jira integration
==============================

To utilize jira/gerrit integration, add tags to your commit message like::

    Closes: bug-1234, bug-1235, bug-1236
    Resolves: bug-1237, bug-1238

The integration script will read commit messages and parse them for these tags.
For any issue mentioned, that issue will be moved, in jira, to the status
"In Review". Then, once the change is merged, any associated ticket mentioned
in "Closes" will be moved to "Closed" and any ticket mentioned in "Resolves"
will be moved to "Resolved".

To scan gerrit changes updated in the past 10 days use::

    flow-tools update-jira-from-gerrit --project my_project \
        --start-time "$(date '+%Y-%m-%d %H:%M:%S' -d '-10 days')" \
        --end-time "$(date '+%Y-%m-%d %H:%M:%S' -d '-10 days')"

To incrementally scan gerrit changes (since the last time you ran this
command or 1 week if this is the first time you've run it)::

    flow-tools increment-jira-from-gerrit --project my_project

For gerrit/jira integration, you can set up a cron job to batch-advance issues
based on their gerrit status::

    crontab -e

Here's a simple cron job that will advance issues on the 12th minute of every
hour::

    PYTHONPATH=/path/to/flow-tools
    # Minute   Hour   Day of Month       Month          Day of Week        Command
    # (0-59)  (0-23)     (1-31)    (1-12 or Jan-Dec)  (0-6 or Sun-Sat)
    12 * * * * flow-tools increment-jira-from-gerrit --project my_project >> /path/to/flow_tools.log

-------------
Configuration
-------------

Configuration is managed by a python file stored at::

    ~/.flowtools/config.py

Here's an example.::


    # URL for the database that sqlalchemy should use. The database is used to
    # cache certain objects fetched from either the gerrit or jira REST APIs
    # and to store some state for doing incremental jobs.
    db_url = "sqlite:////home/user/.flowtools/db.sqlite",

    # Jira rest configuration. These are passed directly as kwargs to the
    # jira rest client constructor.
    jira = {
      "auth" : {
        "url" : "https://company.atlassian.net",
        "username" : "user+robo",
        "password" : "abc123!@#",
      },

      # The nominal flow of a jira ticket from the perspective of gerrit/jira
      # integration. This is used to prevent any "backwards" movement of a
      # ticket in the event that a human being changes the status of a ticket
      # before the integration script does.
      "nominal-flow" : {
        "PROJA": {
          "New": [
            "Open",
            "In Progress",
            "In Review",
            "Verify (QA)",
            "Closed"
          ],
          "Open": [
            "In Progress",
            "In Review",
            "Verify (QA)",
            "Closed"
          ],
          "In Progress": [
            "In Review",
            "Verify (QA)",
            "Closed"
          ],
          "In Review": [
            "Verify (QA)",
            "Closed"
          ],
          "Verify (QA)": [
            "Closed"
          ]
      }


    },

    gerrit = {
      # Gerrit rest configuration. The password is the http password added to
      # gerrit for the account. You can add an http password to an account
      # through either the web UI or command line tools.
      "rest" : {
        "url" : "https://gerrit.company.com",
        "username" : "user+robo",
        "password" : "ABDCEFGHIJKLMNOPQRSTUVWXYZXabcdefghjijklmnopqurst"
      },

      # Gerrit ssh connection information.
      "ssh" : {
        "host" : "gerrit.company.com",
        "port" : 29418
      }
    },

    gerrit_jira = {
      # Maps commit change message tags to jira ticket status that a ticket
      # should be transitioned to in the event that a gerrit change is
      # merged.
      "tag-map": {
        "Closes": "Closed",
        "Resolves": "QA (Resolved)"
      }
    }
