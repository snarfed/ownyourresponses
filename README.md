# ownyourresponses

Creates posts on your web site for your likes, replies, reshares, and event RSVPs on social networks. In [IndieWeb](https://indiewebcamp.com/) terms, [PESOS](https://indiewebcamp.com/PESOS) as a service.

See [PESOS for Bridgy Publish](https://snarfed.org/2015-01-22_pesos-for-bridgy-publish) for background on the motivation.

Currently supports WordPress. I'll port it to [Micropub](https://indiewebcamp.com/micropub) when the [WordPress Micropub plugin](https://github.com/snarfed/wordpress-micropub) is ready.


## Silo API details

**Twitter** has a [streaming API](https://dev.twitter.com/docs/streaming-apis) that sends events for new favorites and tweets (including @-replies and retweets). Bridgy [has used it before](https://github.com/snarfed/bridgy/blob/master/twitter_streaming.py). [It broke when Bridgy went over 100ish Twitter users](https://github.com/snarfed/bridgy/issues/57), but it would work for just one user. Even so, [it's a bit expensive on App Engine](https://github.com/snarfed/bridgy/issues/8), so I'd probably just poll [`/statuses/user_timeline`](https://dev.twitter.com/rest/reference/get/statuses/user_timeline) and [`/favorites/list`](https://dev.twitter.com/rest/reference/get/favorites/list).

**Facebook**'s [Real Time Updates](https://developers.facebook.com/docs/graph-api/real-time-updates/) should work. I've already used it in [ownyourcheckin](https://github.com/snarfed/ownyourcheckin). I'd subscribe to `/user/likes` and `/user/feed`, which I _think_ should include comments. I could also poll those endpoints.

**Google+** has no way to get comments *or* +1s by user, only by post. [API docs](https://developers.google.com/+/api/latest/); [feature request](https://code.google.com/p/google-plus-platform/issues/detail?id=89); [SO answer](http://stackoverflow.com/a/19817758/186123).

**Instagram** can get [likes by user](http://instagram.com/developer/endpoints/users/#get_users_feed_liked), but [not comments](http://stackoverflow.com/a/22002350/186123).
