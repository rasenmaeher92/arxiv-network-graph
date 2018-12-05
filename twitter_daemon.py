"""
Periodically checks Twitter for tweets about arxiv papers we recognize
and logs the tweets into mongodb database "arxiv", under "tweets" collection.
"""

import os
import re
from collections import defaultdict

import pytz
import time
import math
import pickle
import datetime

from dateutil import parser
import tweepy
import pymongo

from utils import Config

# settings
# -----------------------------------------------------------------------------
sleep_time = 60*15 # in seconds, between twitter API calls. Default rate limit is 180 per 15 minutes
max_tweet_records = 15

# convenience functions
# -----------------------------------------------------------------------------
def get_api_connector(consumer_key, consumer_secret):
  auth = tweepy.AppAuthHandler(consumer_key, consumer_secret)
  return tweepy.API(auth, wait_on_rate_limit=True, wait_on_rate_limit_notify=True)

def get_paper(pid):
  return list(db_papers.find({'_id': pid}).limit(1))

def get_keys():
  lines = open('twitter.txt', 'r').read().splitlines()
  return lines

def extract_arxiv_pids(r):
  pids = []
  for u in r.entities['urls']:
    m = re.search('arxiv.org/abs/([0-9]+\.[0-9]+)', u['expanded_url'])
    if m: 
      rawid = m.group(1)
      pids.append(rawid)
  return pids

def get_latest_or_loop(q):
  results = None
  while results is None:
    try:
      results = api.search(q=q, count=100, result_type="mixed")
    except Exception as e:
      print('there was some problem (waiting some time and trying again):')
      print(e)
      time.sleep(sleep_time)
  return results

epochd = datetime.datetime(1970,1,1,tzinfo=pytz.utc) # time of epoch

def tprepro(tweet_text):
  # take tweet, return set of words
  t = tweet_text.lower()
  t = re.sub(r'[^\w\s]','',t) # remove punctuation
  ws = set([w for w in t.split() if not w.startswith('#')])
  return ws


def get_age_decay(age):
  """
  Calc Gauss decay factor - based on elastic search decay function
  :param age: age in hours
  :return: decay factor
  """
  SCALE = 7  # The distance from origin at which the computed factor will equal decay parameter
  DECAY = 0.5  # Defines the score at scale compared to zero (better to update only the scale and keep it fixed
  OFFSET = 1  # the decay function will only compute the decay function for post with a distance greater
  TIME_FACTOR = 0.8  # Reduce the decay over time by taking the TIME FACTOR power of the time value

  if age <= OFFSET:
    return 1
  gamma = math.log(DECAY) / SCALE
  return math.exp(gamma * (age ** TIME_FACTOR))


def calc_papers_twitter_score(papers_to_update):
    papers_to_update = list(set(papers_to_update))
    papers_tweets = list(tweets.find({'pids': {'$in': papers_to_update}}))
    score_per_paper = defaultdict(int)
    links_per_paper = defaultdict(list)
    for t in papers_tweets:
        followers_score = math.log10(t['user_followers_count'] + 1)
        likes_score = math.log10(t['likes'] + 1)
        retweets_score = math.log10(t['retweets'] + 1)
        tot_score = 0.5 * followers_score + 2 * likes_score + 4 * retweets_score

        for cur_p in t['pids']:
            score_per_paper[cur_p] += tot_score
            links_per_paper[cur_p].append({'tname': t['user_screen_name'], 'tid': t['_id'], 'rt': t['retweets'], 'likes': t['likes']})
    return score_per_paper, links_per_paper

def summarize_tweets(papers_to_update):
    score_per_paper, links_per_paper = calc_papers_twitter_score(papers_to_update)
    dnow_utc = datetime.datetime.now()
    dminus = dnow_utc - datetime.timedelta(days=30)
    all_papers = list(db_papers.find({'time_published': {'$gt': dminus}}))
    for cur_p in all_papers:
        new_p_score = score_per_paper.get(cur_p['_id'], 0)
        old_p_score = cur_p.get('twitter_score', 0)
        twitter_score = max(new_p_score, old_p_score)
        if twitter_score > 0:
            age_days = (dnow_utc - cur_p['time_published']).total_seconds() / 86400.0
            twitter_score_decayed = twitter_score * get_age_decay(age_days)
            data = {'twtr_score': twitter_score, 'twtr_score_dec': twitter_score_decayed}
            if cur_p['_id'] in links_per_paper:
                data['twtr_links'] = links_per_paper[cur_p['_id']]
            db_papers.update({'_id': cur_p['_id']}, {'$set': data}, True)


def get_banned():
    banned = {}
    if os.path.isfile(Config.banned_path):
        with open(Config.banned_path, 'r') as f:
            lines = f.read().split('\n')
        for l in lines:
            if l: banned[l] = 1  # mark banned
        print('banning users:', list(banned.keys()))
    return banned

def fetch_tweets():
    banned = get_banned()
    dnow_utc = datetime.datetime.now(datetime.timezone.utc)
    # fetch the latest mentioning arxiv.org
    results = get_latest_or_loop('arxiv.org')
    to_insert = []

    papers_to_update = []

    for r in results:

        arxiv_pids = extract_arxiv_pids(r)
        # arxiv_pids = list(db_papers.find({'_id': {'$in': arxiv_pids}}))  # filter to those that are in our paper db
        if not arxiv_pids: continue  # nothing we know about here, lets move on
        tweet_id_q = {'_id': r.id_str}
        if tweets.find_one(tweet_id_q):
            is_new = False
        else:
            is_new = True

        if r.user.screen_name in banned: continue  # banned user, very likely a bot

        papers_to_update += arxiv_pids

        # create the tweet. intentionally making it flat here without user nesting
        d = r.created_at.replace(tzinfo=pytz.UTC)  # datetime instance
        tweet = {}
        tweet['_id'] = r.id_str
        tweet['pids'] = arxiv_pids  # arxiv paper ids mentioned in this tweet
        tweet['inserted_at_date'] = dnow_utc
        tweet['created_at_date'] = d
        tweet['created_at_time'] = (d - epochd).total_seconds()  # seconds since epoch
        tweet['lang'] = r.lang
        tweet['text'] = r.text
        tweet['retweets'] = r.retweet_count
        tweet['likes'] = r.favorite_count
        tweet['user_screen_name'] = r.user.screen_name
        tweet['user_image_url'] = r.user.profile_image_url
        tweet['user_followers_count'] = r.user.followers_count
        tweet['user_following_count'] = r.user.friends_count
        if is_new:
            to_insert.append(tweet)
        else:
            tweets.update(tweet_id_q, {'$set': tweet}, True)

    if to_insert: tweets.insert_many(to_insert)
    print('processed %d/%d new tweets. Currently maintaining total %d' % (len(to_insert), len(results), tweets.count()))
    return papers_to_update


def main_twitter_fetcher():
    print('testtttt')
    papers_to_update = fetch_tweets()
    summarize_tweets(papers_to_update)


# -----------------------------------------------------------------------------

# authenticate to twitter API
keys = get_keys()
api = get_api_connector(keys[0], keys[1])

# connect to mongodb instance
client = pymongo.MongoClient()
mdb = client.arxiv
tweets = mdb.tweets # the "tweets" collection in "arxiv" database
db_papers = mdb.papers

# main loop
