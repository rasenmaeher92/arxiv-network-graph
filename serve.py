import atexit
import datetime
import logging
import os
import json
import re
import time
import pickle
import argparse
import dateutil.parser
from random import randrange, uniform

from sqlite3 import dbapi2 as sqlite3

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, session, url_for, redirect, \
    render_template, g, flash, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug import check_password_hash, generate_password_hash
import pymongo

from fetch_citations_and_references import fetch_paper_data, send_query
from fetch_papers import fetch_papers_main
from logger import logger_config
from twitter_daemon import main_twitter_fetcher

from utils import safe_pickle_dump, strip_version, isvalidid, Config

# various globals
# -----------------------------------------------------------------------------

# database configuration
if os.path.isfile('secret_key.txt'):
  SECRET_KEY = open('secret_key.txt', 'r').read()
else:
  SECRET_KEY = 'devkey, should be in a file'
app = Flask(__name__)
app.config.from_object(__name__)
limiter = Limiter(app, key_func=get_remote_address, default_limits=["5000 per hour", "100 per minute"])

# -----------------------------------------------------------------------------
# utilities for database interactions 
# -----------------------------------------------------------------------------
# to initialize the database: sqlite3 as.db < schema.sql
def connect_db():
  sqlite_db = sqlite3.connect(Config.database_path)
  sqlite_db.row_factory = sqlite3.Row # to return dicts rather than tuples
  return sqlite_db

def query_db(query, args=(), one=False):
  """Queries the database and returns a list of dictionaries."""
  cur = g.db.execute(query, args)
  rv = cur.fetchall()
  return (rv[0] if rv else None) if one else rv

def get_user_id(username):
  """Convenience method to look up the id for a username."""
  rv = query_db('select user_id from user where username = ?',
                [username], one=True)
  return rv[0] if rv else None

def get_username(user_id):
  """Convenience method to look up the username for a user."""
  rv = query_db('select username from user where user_id = ?',
                [user_id], one=True)
  return rv[0] if rv else None

# -----------------------------------------------------------------------------
# connection handlers
# -----------------------------------------------------------------------------

@app.before_request
def before_request():
  # this will always request database connection, even if we dont end up using it ;\
  g.db = connect_db()
  # retrieve user object from the database if user_id is set
  g.user = None
  if 'user_id' in session:
    g.user = query_db('select * from user where user_id = ?',
                      [session['user_id']], one=True)

@app.teardown_request
def teardown_request(exception):
  db = getattr(g, 'db', None)
  if db is not None:
    db.close()

# -----------------------------------------------------------------------------
# search/sort functionality
# -----------------------------------------------------------------------------

def papers_search(qraw):
    return list(db_papers.find({'$text': {'$search': qraw}}).limit(50))


def papers_similar(pid):
    rawpid = strip_version(pid)
    return []


def papers_from_library():
  out = []
  if g.user:
    # user is logged in, lets fetch their saved library data
    uid = session['user_id']
    user_library = query_db('''select * from library where user_id = ?''', [uid])
    libids = [strip_version(x['paper_id']) for x in user_library]
    out = list(db_papers.find({'_id': {'$in': libids}}).sort("time_updated", pymongo.DESCENDING))
  return out


def papers_filter_version(papers, v):
  if v != '1': 
    return papers # noop
  intv = int(v)
  filtered = [p for p in papers if p['_version'] == intv]
  return filtered

def encode_json(ps, n=10, send_images=True, send_abstracts=True):

  libids = set()
  if g.user:
    # user is logged in, lets fetch their saved library data
    uid = session['user_id']
    user_library = query_db('''select * from library where user_id = ?''', [uid])
    libids = {strip_version(x['paper_id']) for x in user_library}

  ret = []
  for i in range(min(len(ps),n)):
    p = ps[i]
    idvv = '%sv%d' % (p['_rawid'], p['_version'])
    struct = {}
    struct['title'] = p['title']
    struct['pid'] = idvv
    struct['rawpid'] = p['_rawid']
    struct['category'] = p['arxiv_primary_category']['term']
    struct['authors'] = [a['name'] for a in p['authors']]
    struct['link'] = p['link']
    struct['in_library'] = 1 if p['_rawid'] in libids else 0
    if send_abstracts:
      struct['abstract'] = p['summary']
    if send_images:
      struct['img'] = '/static/thumbs/' + idvv + '.pdf.jpg'
    struct['tags'] = [t['term'] for t in p['tags']]
    
    # render time information nicely
    timestruct = dateutil.parser.parse(p['updated'])
    struct['published_time'] = '%s/%s/%s' % (timestruct.month, timestruct.day, timestruct.year)
    timestruct = dateutil.parser.parse(p['published'])
    struct['originally_published_time'] = '%s/%s/%s' % (timestruct.month, timestruct.day, timestruct.year)
    struct['twtr_score_dec'] = p.get('twtr_score_dec', 0)
    struct['twtr_score'] = p.get('twtr_score', 0)
    struct['twtr_links'] = p.get('twtr_links', [])
    # fetch amount of discussion on this paper
    struct['num_discussion'] = comments.count({ 'pid': p['_rawid'] })

    # arxiv comments from the authors (when they submit the paper)
    cc = p.get('arxiv_comment', '')
    if len(cc) > 100:
      cc = cc[:100] + '...' # crop very long comments
    struct['comment'] = cc

    ret.append(struct)
  return ret

# -----------------------------------------------------------------------------
# flask request handling
# -----------------------------------------------------------------------------

def default_context(papers, **kws):
  top_papers = encode_json(papers, args.num_results)

  # prompt logic
  show_prompt = 'no'
  try:
    if Config.beg_for_hosting_money and g.user and uniform(0,1) < 0.05:
      uid = session['user_id']
      entry = goaway_collection.find_one({ 'uid':uid })
      if not entry:
        lib_count = query_db('''select count(*) from library where user_id = ?''', [uid], one=True)
        lib_count = lib_count['count(*)']
        if lib_count > 0: # user has some items in their library too
          show_prompt = 'yes'
  except Exception as e:
    print(e)

  ans = dict(papers=top_papers, numresults=len(papers), totpapers=len(papers), tweets=[], msg='', show_prompt=show_prompt, pid_to_users={})
  ans.update(kws)
  return ans

@app.route('/goaway', methods=['POST'])
def goaway():
  if not g.user: return # weird
  uid = session['user_id']
  entry = goaway_collection.find_one({ 'uid':uid })
  if not entry: # ok record this user wanting it to stop
    username = get_username(session['user_id'])
    print('adding', uid, username, 'to goaway.')
    goaway_collection.insert_one({ 'uid':uid, 'time':int(time.time()) })
  return 'OK'

@app.route("/")
def intmain():
  vstr = request.args.get('vfilter', 'time_published')
  if vstr != 'time_published':
      vstr = 'time_updated'

  papers = list(db_papers.find().sort(vstr, pymongo.DESCENDING).limit(100))
  papers = papers_filter_version(papers, vstr)
  ctx = default_context(papers, render_format='recent',
                        msg='Showing most recent Arxiv papers:')
  return render_template('main.html', **ctx)

@app.route("/<request_pid>")
def rank(request_pid=None):
  if not isvalidid(request_pid):
    return '' # these are requests for icons, things like robots.txt, etc
  papers = papers_similar(request_pid)
  ctx = default_context(papers, render_format='paper')
  return render_template('main.html', **ctx)

@app.route('/notes', methods=['GET'])
def discuss():
  """ return discussion related to a paper """
  pid = request.args.get('id', '') # paper id of paper we wish to discuss
  papers = list(db_papers.find({'_id': pid}))

  # fetch the comments
  comms_cursor = comments.find({ 'pid':pid }).sort([('time_posted', pymongo.DESCENDING)])
  comms = list(comms_cursor)
  for c in comms:
    c['_id'] = str(c['_id']) # have to convert these to strs from ObjectId, and backwards later http://api.mongodb.com/python/current/tutorial.html

  # fetch the counts for all tags
  tag_counts = []
  for c in comms:
    cc = [tags_collection.count({ 'comment_id':c['_id'], 'tag_name':t }) for t in TAGS]
    tag_counts.append(cc);

  # and render
  ctx = default_context(papers, render_format='default', comments=comms, gpid=pid, tags=TAGS, tag_counts=tag_counts)
  return render_template('discuss.html', **ctx)


def get_paper(pid):
    return list(db_papers.find({'_id': pid}).limit(1))


@app.route('/comment', methods=['POST'])
def comment():
  """ user wants to post a comment """
  anon = int(request.form['anon'])

  if g.user and (not anon):
    username = get_username(session['user_id'])
  else:
    # generate a unique username if user wants to be anon, or user not logged in.
    username = 'anon-%s-%s' % (str(int(time.time())), str(randrange(1000)))

  # process the raw pid and validate it, etc
  try:
    pid = request.form['pid']
    cur_p = get_paper(pid)
    if not cur_p: raise Exception("invalid pid")
    version = cur_p[0]['_version'] # most recent version of this paper
  except Exception as e:
    print(e)
    return 'bad pid. This is most likely Andrej\'s fault.'

  # create the entry
  entry = {
    'user': username,
    'pid': pid, # raw pid with no version, for search convenience
    'version': version, # version as int, again as convenience
    'conf': request.form['conf'],
    'anon': anon,
    'time_posted': time.time(),
    'text': request.form['text'],
  }

  # enter into database
  print(entry)
  comments.insert_one(entry)
  return 'OK'

@app.route("/discussions", methods=['GET'])
def discussions():
  # return most recently discussed papers
  comms_cursor = comments.find().sort([('time_posted', pymongo.DESCENDING)]).limit(100)

  # get the (unique) set of papers.
  papers = []
  have = set()
  for e in comms_cursor:
    pid = e['pid']
    cur_p = get_paper(pid)
    if cur_p and not pid in have:
      have.add(pid)
      papers.append(cur_p)

  ctx = default_context(papers, render_format="discussions")
  return render_template('main.html', **ctx)

@app.route('/toggletag', methods=['POST'])
def toggletag():

  if not g.user: 
    return 'You have to be logged in to tag. Sorry - otherwise things could get out of hand FAST.'

  # get the tag and validate it as an allowed tag
  tag_name = request.form['tag_name']
  if not tag_name in TAGS:
    print('tag name %s is not in allowed tags.' % (tag_name, ))
    return "Bad tag name. This is most likely Andrej's fault."

  pid = request.form['pid']
  comment_id = request.form['comment_id']
  username = get_username(session['user_id'])
  time_toggled = time.time()
  entry = {
    'username': username,
    'pid': pid,
    'comment_id': comment_id,
    'tag_name': tag_name,
    'time': time_toggled,
  }

  # remove any existing entries for this user/comment/tag
  result = tags_collection.delete_one({ 'username':username, 'comment_id':comment_id, 'tag_name':tag_name })
  if result.deleted_count > 0:
    print('cleared an existing entry from database')
  else:
    print('no entry existed, so this is a toggle ON. inserting:')
    print(entry)
    tags_collection.insert_one(entry)

  return 'OK'

@app.route("/search", methods=['GET'])
def search():
  q = request.args.get('q', '') # get the search request
  papers = papers_search(q) # perform the query and get sorted documents
  ctx = default_context(papers, render_format="search")
  return render_template('main.html', **ctx)

@app.route('/toptwtr', methods=['GET'])
def toptwtr():
  """ return top papers """
  ttstr = request.args.get('timefilter', 'week') # default is day
  legend = {'day': 1, '3days': 3, 'week': 7, 'month': 30, 'year': 365, 'alltime': 10000}
  days = legend.get(ttstr)
  dnow_utc = datetime.datetime.now()
  dminus = dnow_utc - datetime.timedelta(days=int(days))
  papers, tweets = [], []
  papers = list(db_papers.find({'time_published': {'$gt': dminus}}).sort('twtr_score_dec', pymongo.DESCENDING))
  # for rec in cursor:
  #   if rec['pid'] in db:
  #     papers.append(db[rec['pid']])
  #     tweet = {k:v for k,v in rec.items() if k != '_id'}
  #     tweets.append(tweet)
  ctx = default_context(papers, render_format='toptwtr', tweets=tweets,
                        msg=f'Top papers mentioned on Twitter over last {days} days')
  return render_template('main.html', **ctx)

@app.route('/library')
def library():
  """ render user's library """
  papers = papers_from_library()
  ret = encode_json(papers, 500) # cap at 500 papers in someone's library. that's a lot!
  if g.user:
    msg = '%d papers in your library:' % (len(ret), )
  else:
    msg = 'You must be logged in. Once you are, you can save papers to your library (with the save icon on the right of each paper) and they will show up here.'
  ctx = default_context(papers, render_format='library', msg=msg)
  return render_template('main.html', **ctx)

@app.route('/libtoggle', methods=['POST'])
def review():
  """ user wants to toggle a paper in his library """
  
  # make sure user is logged in
  if not g.user:
    return 'NO' # fail... (not logged in). JS should prevent from us getting here.

  idvv = request.form['pid'] # includes version
  if not isvalidid(idvv):
    return 'NO' # fail, malformed id. weird.
  pid = strip_version(idvv)
  cur_p = get_paper(pid)
  if not cur_p:
    return 'NO' # we don't know this paper. wat

  uid = session['user_id'] # id of logged in user

  # check this user already has this paper in library
  record = query_db('''select * from library where
          user_id = ? and paper_id = ?''', [uid, pid], one=True)
  print(record)

  ret = 'NO'
  if record:
    # record exists, erase it.
    g.db.execute('''delete from library where user_id = ? and paper_id = ?''', [uid, pid])
    g.db.commit()
    #print('removed %s for %s' % (pid, uid))
    ret = 'OFF'
  else:
    # record does not exist, add it.
    rawpid = strip_version(pid)
    g.db.execute('''insert into library (paper_id, user_id, update_time) values (?, ?, ?)''',
        [rawpid, uid, int(time.time())])
    g.db.commit()
    #print('added %s for %s' % (pid, uid))
    ret = 'ON'

  return ret

@app.route('/account')
def account():
    ctx = { 'totpapers': 100 }

    followers = []
    following = []
    # fetch all followers/following of the logged in user
    if g.user:
        username = get_username(session['user_id'])
        
        following_db = list(follow_collection.find({ 'who':username }))
        for e in following_db:
            following.append({ 'user':e['whom'], 'active':e['active'] })

        followers_db = list(follow_collection.find({ 'whom':username }))
        for e in followers_db:
            followers.append({ 'user':e['who'], 'active':e['active'] })

    ctx['followers'] = followers
    ctx['following'] = following
    return render_template('account.html', **ctx)


@app.route('/login', methods=['POST'])
def login():
    """ logs in the user. if the username doesn't exist creates the account """

    if not request.form['username']:
        flash('You have to enter a username')
    elif not request.form['password']:
        flash('You have to enter a password')
    elif get_user_id(request.form['username']) is not None:
        # username already exists, fetch all of its attributes
        user = query_db('''select * from user where
          username = ?''', [request.form['username']], one=True)
        if check_password_hash(user['pw_hash'], request.form['password']):
            # password is correct, log in the user
            session['user_id'] = get_user_id(request.form['username'])
            flash('User ' + request.form['username'] + ' logged in.')
        else:
            # incorrect password
            flash('User ' + request.form['username'] + ' already exists, wrong password.')
    else:
        # create account and log in
        creation_time = int(time.time())
        g.db.execute('''insert into user (username, pw_hash, creation_time) values (?, ?, ?)''',
                     [request.form['username'],
                      generate_password_hash(request.form['password']),
                      creation_time])
        user_id = g.db.execute('select last_insert_rowid()').fetchall()[0][0]
        g.db.commit()

        session['user_id'] = user_id
        flash('New account %s created' % (request.form['username'], ))

    return redirect(url_for('intmain'))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You were logged out')
    return redirect(url_for('intmain'))

@app.route('/network')
def network():
    return render_template('network_vis.html')


@app.route('/citations_network')
def citations_network():
    return render_template('citations_network.html')


@app.route('/categories')
def categories():
    return jsonify(ARXIV_CATEGORIES)


@app.route('/author_papers')
def author_papers():
    authors = json.loads(request.args.get('q', ''))
    papers = list(db_papers.find({'authors.name': {'$in': authors}}).sort("time_published", pymongo.DESCENDING))
    papers = [{'title': p['title'], 'url': p['link']} for p in papers]
    return jsonify(papers)


def add_new_paper_to_db(res):

    sem_sch_papers.update({'_id': res['_id']}, {'$set': res}, True)
    for a in res['authors']:
        sem_sch_authors.update({'_id': a['name']}, {}, True)


def record_request(obj_id, obj_type, ):
    is_first = int(request.args.get('first', 0))
    network_requests.insert_one({'id': obj_id, 'type': obj_type, 'dt': datetime.datetime.utcnow(), 'ip': request.remote_addr,
                                 'session': request.cookies.get('session', ''), 'is_first': is_first})

@app.route('/get_paper')
def get_paper():
    id = request.args.get('id', '') or request.args.get('sem_id', '')
    if id:
        paper = sem_sch_papers.find_one({'$or': [{'_id': id}, {'paperId': id}]})
        if not paper:
            is_arxiv = '.' in id
            paper = send_query({'_id': id}, is_arxiv=is_arxiv)
            if paper:
                add_new_paper_to_db(paper)

        if paper:
            fields = ['title', '_id', 'paper_id', 'authors', 'citations', 'references', 'time_published', 'year']
            res = {f: paper.get(f, None) for f in fields}
            res['id'] = id
            record_request(id, 'paper')
            return jsonify(res)

    return jsonify({'error': 'Paper id is missing'}), 404


@app.route('/get_author')
def get_author():
    name = request.args.get('name', '')
    papers = list(sem_sch_papers.find({'authors.name': name}))
    record_request(name, 'author')
    return jsonify(papers)


@app.route('/autocomplete_2')
def autocomplete_2():
    q = request.args.get('q', '')
    if len(q) <= 1:
        return jsonify([])

    authors = list(sem_sch_authors.find({'_id': {'$regex': re.compile(f'.*{q}.*', re.IGNORECASE)}}).limit(7))
    authors = [{'name': a['_id'], 'type': 'author'} for a in authors]

    papers = list(sem_sch_papers.find({'$or': [{'_id': q}, {'$text': {'$search': q}}]}).limit(7))
    papers = [{'name': p['title'], 'type': 'paper', 'id': p['_id'], 'sem_id': p.get('paperId', '')} for p in papers]

    return jsonify(authors + papers)


@app.route('/autocomplete')
def autocomplete():
    q = request.args.get('q', '')
    if len(q) <= 2:
        return jsonify([])

    authors = list(db_authors.find({'_id': {'$regex': re.compile(f'.*{q}.*', re.IGNORECASE)}}).limit(50))
    authors = sorted(authors, key=lambda x: len(x['papers']), reverse=True)[:5]
    authors = [{'name': a['_id'], 'type': 'author'} for a in authors]

    papers = list(db_papers.find({'title': {'$regex': re.compile(f'.*{q}.*', re.IGNORECASE)}}).sort("time_published", pymongo.DESCENDING).limit(5))
    papers = [{'name': p['title'], 'type': 'paper', 'authors': p['authors']} for p in papers]

    return jsonify(authors + papers)


# -----------------------------------------------------------------------------
# int main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    logger_config()
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--prod', dest='prod', action='store_true', help='run in prod?')
    parser.add_argument('-r', '--num_results', dest='num_results', type=int, default=200,
                        help='number of results to return per query')
    parser.add_argument('--port', dest='port', type=int, default=5000, help='port to serve on')
    args = parser.parse_args()
    logger.info(args)

    if not os.path.isfile(Config.database_path):
        logger.info('did not find as.db, trying to create an empty database from schema.sql...')
        logger.info('this needs sqlite3 to be installed!')
        os.system('sqlite3 as.db < schema.sql')

    logger.info('connecting to mongodb...')
    client = pymongo.MongoClient()
    mdb = client.arxiv
    db_papers = mdb.papers
    db_authors = mdb.authors
    tweets = mdb.tweets
    sem_sch_papers = mdb.sem_sch_papers
    sem_sch_authors = mdb.sem_sch_authors

    network_requests = mdb.network_requests

    comments = mdb.comments
    tags_collection = mdb.tags
    goaway_collection = mdb.goaway
    follow_collection = mdb.follow

    TAGS = ['insightful!', 'thank you', 'agree', 'disagree', 'not constructive', 'troll', 'spam']
    ARXIV_CATEGORIES = json.load(open('relevant_arxiv_categories.json', 'r'))

    scheduler = BackgroundScheduler()
    scheduler.add_job(func=main_twitter_fetcher, trigger="interval", minutes=20)
    scheduler.add_job(func=fetch_papers_main, trigger="interval", hours=2)

    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())

    # start
    if args.prod:
        # run on Tornado instead, since running raw Flask in prod is not recommended
        logger.info('starting tornado!')
        from tornado.wsgi import WSGIContainer
        from tornado.httpserver import HTTPServer
        from tornado.ioloop import IOLoop
        from tornado.log import enable_pretty_logging

        enable_pretty_logging()
        http_server = HTTPServer(WSGIContainer(app))
        http_server.listen(args.port)
        IOLoop.instance().start()
    else:
        logger.info('starting flask!')
        app.debug = False
        app.run(port=args.port, host='0.0.0.0')
