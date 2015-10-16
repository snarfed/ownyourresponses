"""OwnYourResponses: turns likes, replies, etc. into posts on your web site.

Polls your social network activity and creates new posts on your web site (via
Micropub) for public Facebook comments and likes, Instagram likes, and Twitter
@-replies, retweets, and favorites.
"""

__author__ = ['Ryan Barrett <ownyourresponses@ryanb.org>']

import logging
import json
import string
import urllib
import urllib2

from granary import appengine_config
from granary import facebook
from granary import instagram
from granary import microformats2
from granary import source as as_source
from granary import twitter
from oauth_dropins import handlers
from oauth_dropins.webutil import util

from google.appengine.ext import ndb
import webapp2

# Change this to your web site's Micropub endpoint.
# https://indiewebcamp.com/micropub
MICROPUB_ENDPOINT = 'https://snarfed.org/w/?micropub=endpoint'

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

FACEBOOK_ACCESS_TOKEN = appengine_config.read('facebook_access_token')
INSTAGRAM_ACCESS_TOKEN = appengine_config.read('instagram_access_token')
TWITTER_ACCESS_TOKEN = appengine_config.read('twitter_access_token')
TWITTER_ACCESS_TOKEN_SECRET = appengine_config.read('twitter_access_token_secret')
MICROPUB_ACCESS_TOKEN = appengine_config.read('micropub_access_token')


class Response(ndb.Model):
  """Key name is ActivityStreams activity id."""
  activity_json = ndb.TextProperty(required=True)
  post_url = ndb.TextProperty()
  response_body = ndb.TextProperty()
  status = ndb.StringProperty(choices=('started', 'complete'), default='started')
  created = ndb.DateTimeProperty(auto_now_add=True)
  updated = ndb.DateTimeProperty(auto_now=True)


class PollHandler(webapp2.RequestHandler):
  """Poll handler for cron job."""

  def get(self):
    sources = []
    # if FACEBOOK_ACCESS_TOKEN:
    #   sources.append(facebook.Facebook(FACEBOOK_ACCESS_TOKEN))
    if INSTAGRAM_ACCESS_TOKEN:
      sources.append(instagram.Instagram(INSTAGRAM_ACCESS_TOKEN))
    if TWITTER_ACCESS_TOKEN:
      sources.append(twitter.Twitter(TWITTER_ACCESS_TOKEN,
                                     TWITTER_ACCESS_TOKEN_SECRET))

    for source in sources:
      self.poll(source)

  def poll(self, source):
    activities = source.get_activities(group_id=as_source.SELF, fetch_likes=True)
    resps = ndb.get_multi(ndb.Key('Response', util.trim_nulls(a['id']))
                          for a in activities)
    resps = {r.key.id(): r for r in resps if r}

    for activity in activities:
      obj = activity.get('object', {})

      # have we already posted or started on this response?
      resp = resps.get(activity['id'])
      mf2 = microformats2.object_to_json(activity)
      mf2_props = microformats2.first_props(mf2.get('properties', {}))
      type = as_source.object_type(activity)

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

      # make micropub call to create post
      # http://indiewebcamp.com/micropub
      #
      # include access token in both header and post body for compatibility
      # with servers that only support one or the other (for whatever reason).
      headers = {'Authorization': 'Bearer ' + MICROPUB_ACCESS_TOKEN}
      data = mf2_props
      data.update({
        'access_token': MICROPUB_ACCESS_TOKEN,
        'h': 'entry',
        'category[]': CATEGORIES.get(type),
        'content': self.render(source, activity, base),
        'name': base.get('content') or base.get('object', {}).get('content')
      })
      for prop in 'url', 'author':
        if prop in data:
          del data[prop]

      result = self.urlopen(MICROPUB_ENDPOINT, headers=headers,
                            data=util.trim_nulls(data))

      resp.post_url = result.info().get('Location')
      logging.info('Created new post: %s', resp.post_url)
      resp.response_body = result.read()
      logging.info('Response body: %s', resp.response_body)

      resp.status = 'complete'
      resp.put()

      # uncomment for testing
      # return

    # end loop over activities

  @staticmethod
  def render(source, activity, base):
    obj = activity.get('object') or activity
    content = microformats2.render_content(obj)
    embed = source.embed_post(base)

    type = as_source.object_type(activity)
    content = activity.get('content', '')
    if type == 'share' and not content:
      content = 'retweeted this.'

    rendered = embed + content if type == 'comment' else content + embed

    mf2_class = {'like': 'u-like-of',
                 'share': 'u-repost-of',
                 }.get(type, 'in-reply-to')
    url = base.get('url')
    rendered += '\n<a class="%s" href="%s"></a>' % (mf2_class, url)

    return rendered

  def urlopen(self, url, data=None, headers=None):
    data = {key: val.encode('utf-8') for key, val in data.items()}

    logging.info('Fetching %s with headers %s, data %s', url, headers, data)
    if headers:
      url = urllib2.Request(url, headers=headers)
    if data:
      data = urllib.urlencode(data)

    try:
      return urllib2.urlopen(url, timeout=600, data=data)
    except urllib2.HTTPError, e:
      logging.error('%s %s', e.reason, e.read())
      raise
    except urllib2.URLError, e:
      logging.error(e.reason)
      raise


application = webapp2.WSGIApplication(
  [('/cron/poll', PollHandler),
   ], debug=False)
