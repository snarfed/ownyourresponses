"""OwnYourCheckin: handler for Facebook Real Time Update for /user/feed.

https://developers.facebook.com/docs/graph-api/real-time-updates/v2.2#receiveupdates

Creates and publishes a new WordPress post via the JSON API. Requires Jetpack
for self-hosted WordPress.

test command line:

curl localhost:8080/user_feed_update \
  -d '{"object":"user","entry":[{"changed_fields":["feed"]}]}'
"""

__author__ = ['Ryan Barrett <ownyourcheckin@ryanb.org>']

import datetime
import logging
import json
import operator
import string
import urllib
import urllib2

from google.appengine.ext import ndb
import webapp2


def read(filename):
  with open(filename) as f:
    return f.read().strip()

FACEBOOK_APP_ID = read('facebook_app_id')
FACEBOOK_ACCESS_TOKEN = read('facebook_access_token')
FACEBOOK_VERIFY_TOKEN = 'fluffernutter'

WORDPRESS_SITE_DOMAIN = 'snarfed.org'
WORDPRESS_ACCESS_TOKEN = read('wordpress.com_access_token')


class Checkin(ndb.Model):
  """Key name is Facebook checkin URL."""
  checkin_json = ndb.TextProperty(required=True)
  post_json = ndb.TextProperty()
  status = ndb.StringProperty(choices=('started', 'complete'), default='started')
  created = ndb.DateTimeProperty(auto_now_add=True)
  updated = ndb.DateTimeProperty(auto_now=True)


class UpdateHandler(webapp2.RequestHandler):

  def get(self):
    """Verifies a request from FB to confirm this endpoint.

    https://developers.facebook.com/docs/graph-api/real-time-updates/v2.2#setupget
    """
    logging.info('Verification request: %s', self.request.params)
    if self.request.get('hub.verify_token') == FACEBOOK_VERIFY_TOKEN:
      self.response.headers['Content-Type'] = 'text/plain'
      self.response.write(self.request.get('hub.challenge') + '\r\n')

  def post(self):
    """Converts an FB checkin to a new WP post.

    Example request body:

    {"object" : "user",
     "entry" : [{
       "uid" : "10101456587354063",
       "time" : 1421128210,
       "id" : "10101456587354063",
       "changed_fields" : ["feed"],
     }]
    }

    The entry.id field is just an obfuscated form of the user id. So, I have to
    fetch /user/feed each time and keep track of the posts I've seen. :(
    ...or just find the first checkin in the last day, and give up if none (the
    bootstrap case).
    """
    logging.info('Update request: %s', self.request.body)
    req = json.loads(self.request.body)

    if (req.get('object') != 'user' or
        'feed' not in req.get('entry', [{}])[0].get('changed_fields', [])):
      return

    # load the user's recent FB posts. look for a checkin within the last day.
    feed = self.fb_get('me/feed')
    for post in feed.get('data', []):
      # both facebook and app engine timestamps default to UTC
      place = post.get('place')
      created = post.get('created_time')
      if (place and created and
          datetime.datetime.strptime(created, '%Y-%m-%dT%H:%M:%S+0000') >=
          datetime.datetime.now() - datetime.timedelta(days=1)):
        checkin_json = json.dumps(post, indent=2)
        logging.info('Found checkin:\n%s', checkin_json)
        break
    else:
      logging.info('No checkin found within the last day. Aborting.')
      return

    # have we already posted this checkin?
    post_url = 'https://www.facebook.com/%s/posts/%s' % tuple(post['id'].split('_'))
    checkin = Checkin.get_by_id(post_url)
    if checkin and checkin.status == 'complete':
      logging.info("We've already posted this checkin! Bailing out.")
      return
    elif not checkin:
      logging.info('First time seeing this checkin.')
      checkin = Checkin(id=post_url, checkin_json=checkin_json)
      checkin.put()

    # generate WP post body
    people = ''
    with_tags = post.get('with_tags', {}).get('data', [])
    if with_tags:
      people = ' with ' + ','.join(
          '<a class="h-card" href="https://www.facebook.com/%(id)s">'
            '%(name)s</a>' % tag
          for tag in with_tags)

    image = image_url = ''
    object_id = post.get('object_id')
    if post.get('type') == 'photo' and object_id:
      obj = self.fb_get(object_id)
      image_url = max(obj.get('images', []),
                      key=operator.itemgetter('height'))['source']
      # image = '<a href="%s"><img class="alignnone size-full" src="%s"/></a>' % \
      #         (image_url, image_url)

    content = string.Template("""\
$message
<blockquote class="h-as-checkin">
At <a class="h-card p-location"
      href="https://www.facebook.com/$id">$name</a>$people.
</blockquote>
<a class="u-syndication" href="$post_url"></a>
""").substitute(message=post.get('message'), post_url=post_url, people=people, **place)

    # make WP API call to create post
    url = ('https://public-api.wordpress.com/rest/v1.1/sites/%s/posts/new' %
           WORDPRESS_SITE_DOMAIN)
            # 'media_urls[]': '',
    headers = {'authorization': 'Bearer ' + WORDPRESS_ACCESS_TOKEN}
    resp = self.urlopen_json(url, headers=headers, data={
      # uncomment for testing
      # 'status': 'private',
      'content': content,
      'media_urls[]': image_url})
    post_json = json.dumps(resp, indent=2)
    logging.info('Response:\n%s', post_json)

    # store success in datastore
    # TODO: make this transactional with the wordpress post via storing and
    # querying extra metadata in wp.
    checkin.post_json = post_json
    checkin.status = 'complete'
    checkin.put()

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

  def fb_get(self, path):
    return self.urlopen_json('https://graph.facebook.com/%s?access_token=%s' %
                             (path, FACEBOOK_ACCESS_TOKEN))


application = webapp2.WSGIApplication(
  [('/user_feed_update', UpdateHandler),
   ], debug=False)
