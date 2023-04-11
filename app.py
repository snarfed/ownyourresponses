"""OwnYourResponses: turns likes, replies, etc. into posts on your web site.

Polls your social network activity and creates new posts on your web site (via
Micropub) for public Facebook comments and likes, Instagram likes, and Twitter
@-replies, retweets, and favorites.
"""
import logging
import json
import urllib.error, urllib.parse, urllib.request

from flask import Flask
from google.cloud import ndb
from granary import (
  facebook,
  instagram,
  microformats2,
  source as gr_source,
  twitter,
)
from oauth_dropins.webutil import (
    appengine_info,
    appengine_config,
    flask_util,
    util,
)
from oauth_dropins.webutil.util import json_loads

# Change this to your web site's Micropub endpoint.
# https://indiewebcamp.com/micropub
if appengine_config.DEBUG:
  MICROPUB_ENDPOINT = 'http://localhost/wp-json/micropub/1.0/endpoint'
  MICROPUB_ACCESS_TOKEN = util.read('micropub_access_token_local')
else:
  MICROPUB_ENDPOINT = 'https://snarfed.org/wp-json/micropub/1.0/endpoint'
  MICROPUB_ACCESS_TOKEN = util.read('micropub_access_token')

# ActivityStreams objectTypes and verbs to create posts for. You can add or
# remove types here to control what gets posted to your site.
TYPES = ('like', 'comment', 'share', 'rsvp-yes', 'rsvp-no', 'rsvp-maybe')

# The category to include with each response type. If you don't want categories
# for any (or all) types, just remove them.
CATEGORIES = {
  'like': 'like',
  'comment': 'reply',
  'share': 'repost',
  'rsvp-yes': 'rsvp',
  'rsvp-no': 'rsvp',
  'rsvp-maybe': 'rsvp',
}

FACEBOOK_ACCESS_TOKEN = util.read('facebook_access_token')
INSTAGRAM_ACCESS_TOKEN = util.read('instagram_access_token')
TWITTER_ACCESS_TOKEN = util.read('twitter_access_token')
TWITTER_ACCESS_TOKEN_SECRET = util.read('twitter_access_token_secret')
TWITTER_SCRAPE_HEADERS = json_loads(util.read('twitter_scrape_headers.schnarfed.json'))


# Flask app
app = Flask('ownyourresponses')
app.template_folder = './templates'
app.config.from_mapping(
    ENV='development' if appengine_info.DEBUG else 'PRODUCTION',
    CACHE_TYPE='SimpleCache',
    SECRET_KEY=util.read('flask_secret_key'),
    JSONIFY_PRETTYPRINT_REGULAR=True,
)
app.register_error_handler(Exception, flask_util.handle_exception)

app.wsgi_app = flask_util.ndb_context_middleware(
    app.wsgi_app, client=appengine_config.ndb_client)


class Response(ndb.Model):
  """Key name is ActivityStreams activity id."""
  activity_json = ndb.TextProperty(required=True)
  post_url = ndb.TextProperty()
  response_body = ndb.TextProperty()
  status = ndb.StringProperty(choices=('started', 'complete'), default='started')
  created = ndb.DateTimeProperty(auto_now_add=True)
  updated = ndb.DateTimeProperty(auto_now=True)


@app.route('/cron/poll')
def poll():
  """Poll handler for cron job."""
  # if FACEBOOK_ACCESS_TOKEN:
  #   sources.append(facebook.Facebook(FACEBOOK_ACCESS_TOKEN))
  # if INSTAGRAM_ACCESS_TOKEN:
  #   sources.append(instagram.Instagram(INSTAGRAM_ACCESS_TOKEN))
  source = twitter.Twitter(TWITTER_ACCESS_TOKEN,
                           TWITTER_ACCESS_TOKEN_SECRET,
                           scrape_headers=TWITTER_SCRAPE_HEADERS)

  activities = source.get_activities(group_id=gr_source.SELF, fetch_likes=True)
  resps = ndb.get_multi(ndb.Key('Response', util.trim_nulls(a['id']))
                        for a in activities)
  resps = {r.key.id(): r for r in resps if r}

  last_exception = None
  for activity in activities:
    obj = activity.get('object', {})

    # have we already posted or started on this response?
    resp = resps.get(activity['id'])
    mf2 = microformats2.object_to_json(activity)
    mf2_props = microformats2.first_props(mf2.get('properties', {}))
    type = gr_source.object_type(activity)

    if mf2_props.get('in-reply-to'):
      type = 'comment'  # twitter reply
    if type not in TYPES or (resp and resp.status == 'complete'):
      continue
    elif resp:
      logging.info('Retrying %s', resp)
    else:
      resp = Response.get_or_insert(activity['id'],
                                    activity_json=json.dumps(activity))
      logging.info('Created new Response: %s', resp)

    base_id = source.base_object(activity)['id']
    base = source.get_activities(activity_id=base_id)[0]
    # logging.info(json.dumps(base, indent=2))

    # make micropub call to create post
    # http://indiewebcamp.com/micropub
    #
    # include access token in both header and post body for compatibility
    # with servers that only support one or the other (for whatever reason).
    headers = {'Authorization': 'Bearer ' + MICROPUB_ACCESS_TOKEN}
    data = {
      'access_token': MICROPUB_ACCESS_TOKEN,
      'h': 'entry',
      'category[]': CATEGORIES.get(type),
      'content[html]': render(source, activity, base),
      'name': base.get('content') or base.get('object', {}).get('content'),
    }
    for key in 'in-reply-to', 'like-of', 'repost-of', 'published', 'updated':
      val = mf2_props.get(key)
      if val:
        data[key] = microformats2.get_string_urls([val])[0]

    try:
      result = urlopen(MICROPUB_ENDPOINT, util.trim_nulls(data), headers=headers)
    except urllib.error.HTTPError as exception:
      last_exception = exception
      logging.exception('%s %s', exception.reason, exception.read())
      continue
    except urllib.error.URLError as exception:
      last_exception = exception
      logging.exception(exception.reason)
      continue

    resp.post_url = result.info().get('Location')
    logging.info('Created new post: %s', resp.post_url)
    resp.response_body = result.read()
    logging.info('Response body: %s', resp.response_body)

    resp.status = 'complete'
    resp.put()

    # uncomment for testing
    # return

  # end loop over activities
  return ('Failed, see logs', 500) if last_exception else 'OK'

def render(source, activity, base):
  obj = activity.get('object') or activity
  content = microformats2.render_content(obj)
  embed = source.embed_post(base)

  type = gr_source.object_type(activity)
  content = activity.get('content', '')
  if type == 'share' and not content:
    content = 'retweeted this.'

  rendered = embed + content if type == 'comment' else content + embed

  mf2_class = {'like': 'u-like-of',
               'share': 'u-repost-of',
               }.get(type, 'in-reply-to')
  url = (obj.get('inReplyTo') or [{}])[0].get('url') or base.get('url')
  rendered += """
<a class="%s" href="%s"></a>
<a class="u-syndication" href="%s"></a>
""" % (mf2_class, url, activity.get('url'))

  return rendered

def urlopen(url, data, headers=None):
  data = {key: val for key, val in data.items()}
  data = urllib.parse.urlencode(data).encode()

  logging.info('Fetching %s with headers %s, data %s', url, headers, data)
  if headers:
    url = urllib.request.Request(url, data=data, headers=headers)
  return urllib.request.urlopen(url, timeout=600, data=data)
