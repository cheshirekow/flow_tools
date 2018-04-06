import urllib

import pygerrit2.rest
import requests

class Configuration(object):
  def __init__(self, rest, ssh):
    self.rest = rest
    self.ssh = ssh

def get_gerrit(url, username, password):
  """
  Return a gerrit rest client object basedon the configuration.
  """
  auth = requests.auth.HTTPDigestAuth(username, password)
  return pygerrit2.rest.GerritRestAPI(url=url, auth=auth)


def get_gerrit_change_id(commit):
  """Parse the commit message to get the gerrit change id."""

  for line in commit.message.splitlines():
    parts = line.strip().split(':', 1)
    if len(parts) != 2:
      continue
    if parts[0] == 'Change-Id':
      return parts[1].strip()

  return None

def gerrit_query(**filters):
  """
  Format a query string given gerrit query filters. The query string is composed
  of ulr-encoded-space (i.e. '+') separated key:value pairs. The value will be
  quoted if it contains whitespace like key:"value x".
  """
  pairs = []
  for key in sorted(filters.keys()):
    value = urllib.quote_plus(filters[key])
    if '+' in value:
      pairs.append('{}:"{}"'.format(key, value))
    else:
      pairs.append('{}:{}'.format(key, value))
  return '+'.join(pairs)


def get_changes_from_range(gerrit_client, project, start_time, end_time,
                           offset=0):
  """
  Call out to the gerrit REST API to get a list of changes that were updated
  in the time period for the given project.
  """
  search_query = gerrit_query(
      project=project, after=start_time, before=end_time)

  query_string = urllib.urlencode([  # ('q', search_query),
      ('o', 'CURRENT_REVISION'),
      ('o', 'LABELS'),
      ('o', 'DETAILED_LABELS'),
      ('o', 'DETAILED_ACCOUNTS'),
      ('start', offset)])

  return gerrit_client.get('/changes/?q={}&{}'
                           .format(search_query, query_string))


def get_message_meta(gerrit_client, change_id, revision):
  """
  Call out to gerrit REST API to get the commit message for the most recent
  revision of a a change, and then scan the commit message for the metadata
  tags. Return a dictionary of metadata found.

  The meta-data keys this function understands are:
    * ChangeId
    * Base-Branch
    * Feature-Branch
    * Relative-To-Branch
    * Closes
    * Resolves

  Closes and Resolves are handled differently then the rest. They may be
  written more than once in the commit message and the contents will be
  merged. The contents are expected to be a comma separated list of strings.
  The output dictionary will contain the separated list of strings.
  """

  parsed_details = gerrit_client.get('changes/{}/revisions/{}/commit'
                                     .format(change_id, revision))

  if 'message' not in parsed_details:
    raise RuntimeError('Message is not a field in returned json')

  result = dict(Closes=[], Resolves=[])
  for line in parsed_details['message'].splitlines():
    parts = line.split(':', 1)
    if len(parts) == 2:
      key, value = parts
      if key in ['Feature-Branch', 'Base-Branch', 'Relative-To-Branch',
                 'ChangeId']:
        result[key] = value.strip()
      elif key in ['Closes', 'Resolves']:
        issues = [item.strip() for item in value.strip().split(',')]
        result[key].extend(issues)

  return result
