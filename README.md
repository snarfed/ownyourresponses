# ownyourresponses

Creates posts on your web site for your likes, replies, reshares, and event RSVPs on social networks. In [IndieWeb](https://indiewebcamp.com/) terms, [PESOS](https://indiewebcamp.com/PESOS) as a service.

See [PESOS for Bridgy Publish](https://snarfed.org/2015-01-22_pesos-for-bridgy-publish) for background on the motivation.

Uses [Micropub](https://indiewebcamp.com/micropub). Your web site must have a
Micropub endpoint.
([Here's one for WordPress](https://github.com/snarfed/wordpress-micropub), for
example.)

This project is placed in the public domain. You may also use it under the [CC0 license](http://creativecommons.org/publicdomain/zero/1.0/).


## Setup

Setup
---

1. Clone this repo.

1. Change `MICROPUB_ENDPOINT` in `app.py` to your site's endpoint.

1. Generate a [Micropub](https://indiewebcamp.com/micropub) access token for
your web site.

1. Put it in a file called `micropub_access_token` in the repo root directory.

1. Create a
[Twitter app](https://apps.twitter.com/app/new) and an
[Instagram app](http://instagram.com/developer/clients/manage/). (No Facebook
yet, since their API doesn't expose your recent likes or comments.)

1. Put their app ids and secrets and access tokens in the repo root directory in
files named `twitter_app_key`, `twitter_app_secret`, `twitter_access_token`,
`instagram_client_id`, `instagram_client_secret`, and `instagram_access_token`.
[Details here.](https://github.com/snarfed/oauth-dropins/blob/master/appengine_config.py)

1. Create an [App Engine](http://appengine.google.com/) app, replace
`ownyourresponses` in `app.yaml` with your app id, and deploy.

...and you're done! Comment or like or retweet something, and it should
automatically create a new post on your web site.


## Silo API details

### Twitter

Twitter has a [streaming API](https://dev.twitter.com/docs/streaming-apis) that sends events for new favorites and tweets (including @-replies and retweets). Bridgy [has used it before](https://github.com/snarfed/bridgy/blob/master/twitter_streaming.py). [It broke when Bridgy went over 100ish Twitter users](https://github.com/snarfed/bridgy/issues/57), but it would work for just one user. Even so, [it's a bit expensive on App Engine](https://github.com/snarfed/bridgy/issues/8), so I'd probably just poll [`/statuses/user_timeline`](https://dev.twitter.com/rest/reference/get/statuses/user_timeline) and [`/favorites/list`](https://dev.twitter.com/rest/reference/get/favorites/list).

### Google+

Google+ has no way to get comments *or* +1s by user, only by post. [API docs](https://developers.google.com/+/api/latest/); [feature request](https://code.google.com/p/google-plus-platform/issues/detail?id=89); [SO answer](http://stackoverflow.com/a/19817758/186123).

### Instagram

Instagram can get [likes by user](http://instagram.com/developer/endpoints/users/#get_users_feed_liked), but [not comments](http://stackoverflow.com/a/22002350/186123).

### Facebook

Facebook's [Real Time Updates](https://developers.facebook.com/docs/graph-api/real-time-updates/) should work. I've already used it in [ownyourcheckin](https://github.com/snarfed/ownyourcheckin). I'd subscribe to `/user/likes` and `/user/feed`, which I _think_ should include likes and comments. I could also poll those endpoints.

...ugh, except they only tell me *that* I liked or commented on something, not *what* I liked or commented on. Here are example objects from those API endpoints:

```json
{
  "id": "212038_10101426802642863",
  "from": {"id": "212038", "name": "Ryan Barrett"},
  "story": "Ryan Barrett likes a post.",
  "story_tags": {...},
  "type": "status",
  "created_time": "2014-12-26T17:41:20+0000",
  "updated_time": "2014-12-26T17:41:20+0000"
}

{
  "id": "212038_10101488100217033",
  "from": {"id": "212038", "name": "Ryan Barrett"},
  "story": "Ryan Barrett commented on his own photo.",
  "story_tags": {...},
  "type": "status",
  "created_time": "2015-02-02T16:40:44+0000",
  "updated_time": "2015-02-02T16:40:44+0000"
}
```

I can generate links from the ids that go to the appropriate stories, e.g. https://www.facebook.com/212038/posts/10101426802642863 and https://www.facebook.com/212038/posts/10101488100217033 , but I can't get the story or comment contents via the API. :(

_Update:
[They fixed this in API v2.3!](https://developers.facebook.com/docs/apps/changelog#v2_3)_
> As of March 25, 2015 We now send content in Page real-time updates (RTUs). Previously, only the object's ID was in the RTU payload. Now we include content in addition to the ID including: statuses, posts, shares, photos, videos, milestones, likes and comments.
