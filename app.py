"""OwnYourResponses: turns likes, replies, etc. into posts on your web site.

Polls your social network activity and creates new posts on your WordPress site
for public Facebook comments and likes, Instagram likes, and Twitter @-replies,
retweets, and favorites.

Uses WordPress's JSON API, which requires the Jetpack plugin for self-hosted
WordPress.
"""

__author__ = ['Ryan Barrett <ownyourresponses@ryanb.org>']

import logging
import json
import string
import urllib
import urllib2

from activitystreams import appengine_config
from activitystreams import facebook
from activitystreams import instagram
from activitystreams import microformats2
from activitystreams import source as as_source
from activitystreams import twitter
from activitystreams.oauth_dropins import handlers
from activitystreams.oauth_dropins.webutil import util

from google.appengine.ext import ndb
import webapp2

# Change this to your WordPress site's domain.
WORDPRESS_SITE_DOMAIN = 'snarfed.org'

# ActivityStreams objectTypes and verbs to create posts for. You can add or
# remove types here to control what gets posted to your site.
TYPES = ('like', 'comment', 'share', 'rsvp-yes', 'rsvp-no', 'rsvp-maybe')

# Change these to the WordPress category ids or names you want to attach to each
# type. If you don't want to attach categories to any types, just remove them.
WORDPRESS_CATEGORIES = {
  'like': 27,
  'comment': 23,
  'share': 28,
  'rsvp-yes': 29,
  'rsvp-no': 29,
  'rsvp-maybe': 29,
}

FACEBOOK_ACCESS_TOKEN = appengine_config.read('facebook_access_token')
INSTAGRAM_ACCESS_TOKEN = appengine_config.read('instagram_access_token')
TWITTER_ACCESS_TOKEN = appengine_config.read('twitter_access_token')
TWITTER_ACCESS_TOKEN_SECRET = appengine_config.read('twitter_access_token_secret')
WORDPRESS_ACCESS_TOKEN = appengine_config.read('wordpress.com_access_token')


class Response(ndb.Model):
  """Key name is ActivityStreams activity id."""
  activity_json = ndb.TextProperty(required=True)
  post_json = ndb.TextProperty()
  status = ndb.StringProperty(choices=('started', 'complete'), default='started')
  created = ndb.DateTimeProperty(auto_now_add=True)
  updated = ndb.DateTimeProperty(auto_now=True)


class PollHandler(webapp2.RequestHandler):
  """Poll handler for cron job."""

  def get(self):
    sources = []
    if FACEBOOK_ACCESS_TOKEN:
      sources.append(facebook.Facebook(FACEBOOK_ACCESS_TOKEN))
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
      type = as_source.object_type(activity)
      if activity.get('context', {}).get('inReplyTo'):
        type = 'comment'  # twitter reply
      if type not in TYPES or (resp and resp.status == 'complete'):
        continue
      elif resp:
        logging.info('Retrying %s', resp)
      else:
        resp = Response.get_or_insert(activity['id'],
                                      activity_json=json.dumps(activity))
        logging.info('Created new Response: %s', resp)

      # make WP API call to create post
      # https://developer.wordpress.com/docs/api/1.1/post/sites/%24site/posts/new/
      url = ('https://public-api.wordpress.com/rest/v1.1/sites/%s/posts/new' %
             WORDPRESS_SITE_DOMAIN)
      headers = {'authorization': 'Bearer ' + WORDPRESS_ACCESS_TOKEN}
      post = self.urlopen_json(url, headers=headers, data={
        # uncomment for testing
        # 'status': 'private',
        'content': self.render(source, activity),
        # 'media_urls[]': activity.get('image') or obj.get('image'),
        'categories': WORDPRESS_CATEGORIES.get(type, ''),
      })
      post_json = json.dumps(post, indent=2)
      logging.info('Created new post on %s: %s', WORDPRESS_SITE_DOMAIN, post_json)

      # store success in datastore
      resp.post_json = post_json
      resp.status = 'complete'
      resp.put()

      # uncomment for testing
      # return

  @staticmethod
  def render(source, activity):
    embed = source.embed_post(activity.get('object') or activity)
    type = as_source.object_type(activity)
    content = activity.get('content', '')
    if type == 'share' and not content:
      content = 'retweeted this.'
    return embed + content if type == 'comment' else content + embed

  def urlopen_json(self, url, data=None, headers=None):
    logging.info('Fetching %s with data %s', url, data)
    if headers:
      url = urllib2.Request(url, headers=headers)
    if data:
      data = urllib.urlencode(data)

    try:
      resp = urllib2.urlopen(url, timeout=600, data=data).read()
      return json.loads(resp)
    except urllib2.URLError, e:
      logging.error(e.reason)
      raise
    except ValueError, e:
      logging.error('Non-JSON response: %s', resp)
      raise


application = webapp2.WSGIApplication(
  [('/cron/poll', PollHandler),
   ], debug=False)
