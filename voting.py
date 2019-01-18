import datetime
import json
import logging
import re
import threading
import uuid

import pymongo
import praw
from flask import Blueprint, render_template, jsonify, request, make_response

from reddit_utils import create_reddit_api, edit_post

voting_app = Blueprint('voting',__name__)
BASE_PATH = '/wayr'
VOTING_COOKIE = 'voting_cookie'
logger = logging.getLogger(__name__)
client = pymongo.MongoClient()
mdb = client.arxiv
db_papers = mdb.papers
db_votes = mdb.votes

MAX_ITEMS = 20

tot_votes = 0
last_reddit_update = None


reddit_api = create_reddit_api()


@voting_app.route(BASE_PATH)
def wayr():
    resp = make_response(render_template('wayr.html'))
    resp.set_cookie(VOTING_COOKIE, str(uuid.uuid4()))
    return resp


def publish_dt_str(p):
    timestruct = p.get('time_published')
    return '{}/{}/{}'.format(timestruct.month, timestruct.day, timestruct.year)


def papers_json(paper_votes, papers_data):
    global tot_votes
    papers = [{'name': p['title'], 'id': p['_id'], 'url': p['link'], 'prct': int(100 * paper_votes.get(p['_id'], 0) / tot_votes),
               'value': paper_votes.get(p['_id'], 0), 'date': publish_dt_str(p)} for p in papers_data]
    return {'data': papers}


@voting_app.route(f"{BASE_PATH}/current_votes")
def current_votes():
    paper_votes = get_votes_summary()
    p_ids = list(paper_votes.keys())
    papers_data = db_papers.find({'_id': {'$in': p_ids}})
    papers_data = sorted(papers_data, key=lambda x: paper_votes.get(x['_id'], 0), reverse=True)
    return jsonify(papers_json(paper_votes, papers_data))


def get_votes_summary(p_ids=None):
    global tot_votes
    now = datetime.datetime.utcnow()
    max_age = now - datetime.timedelta(days=7)
    if p_ids:
        query = {'$and': [{'dt': {'$gt': max_age}}, {'pid': {'$in': p_ids}}]}
    else:
        query = {'dt': {'$gt': max_age}}

    paper_votes = db_votes.aggregate([
        {'$match': query},
        {'$group': {'_id': "$pid", 'total': {'$sum': 1}}},
        {'$sort': {'total': -1}},
        {'$limit': MAX_ITEMS}
    ])

    paper_votes = {p['_id']: p['total'] for p in paper_votes}
    tot_votes = max(sum(paper_votes.values()), 1)
    return paper_votes


@voting_app.route(f'{BASE_PATH}/autocomplete')
def autocomplete():
    q = request.args.get('q', '')
    if len(q) <= 1:
        return jsonify({'data': []})

    papers = db_papers.find({'$or': [{'_id': q}, {'$text': {'$search': q}}]}, {'score': {'$meta': "textScore"}})
    papers = list(papers.sort([('score', {'$meta': 'textScore'})]).limit(MAX_ITEMS))
    p_ids = [p['_id'] for p in papers]
    paper_votes = get_votes_summary(p_ids)
    return jsonify(papers_json(paper_votes, papers))


@voting_app.route(f"{BASE_PATH}/vote", methods=['POST'])
def vote():
    ids = request.json.get('ids', [])
    cookie = request.cookies.get(VOTING_COOKIE, '')
    prev_votes = db_votes.find({'$and': [{'$or': [{'cookie': cookie}, {'ip': request.remote_addr}]}, {'pid': {'$in': ids}}]}, {'_id': 0, 'pid': 1})
    prev_votes = set([v['pid'] for v in prev_votes])
    inserted_data = [{'pid': d, 'dt': datetime.datetime.utcnow(), 'ip': request.remote_addr, 'cookie': cookie} for d in ids if d not in prev_votes]
    if inserted_data:
        db_votes.insert_many(inserted_data)
        reddit_thread = threading.Thread(target=update_reddit_post)
        reddit_thread.start()

    return jsonify({'message': 'Thanks for voting!'})


def clean_text(text):
    return re.sub(' +', ' ', text.replace('\n', ' '))


def get_reddit_post_id():
    try:
        return open('reddit_post.txt', 'r').read()
    except Exception as e:
        logger.error('Failed to read file - {}'.format(e))
    return None


def update_reddit_post():
    global last_reddit_update

    now = datetime.datetime.utcnow()
    max_age = now - datetime.timedelta(minutes=10)
    if last_reddit_update and last_reddit_update > max_age:
        logger.info('Reddit post was updated recently')
        return

    post_id = get_reddit_post_id()
    if not post_id:
        return

    # title = "Machine Learning - WAYR (What Are You Reading) - Voting and Discussion"
    body_base = """This is a place to discuss machine learning research papers that you're reading this week. 
    
You can vote or add a new paper and this post will be updated automatically. It's highly recommended to elaborate and share your thoughts in the comments.
\n
**Vote here:** https://www.lyrn.ai/wayr


---

|Paper|Score|
|--|--|
"""
    final_note = 'Code is [here](https://github.com/ranihorev/arxiv-network-graph). Feedback and feature requests are required :)'
    paper_votes = get_votes_summary()
    p_ids = list(paper_votes.keys())
    papers_data = db_papers.find({'_id': {'$in': p_ids}})
    papers_data = sorted(papers_data, key=lambda x: paper_votes.get(x['_id'], 0), reverse=True)
    papers = papers_json(paper_votes, papers_data)['data']

    body = '\n'.join(['| [{}]({}) | {}% |'.format(clean_text(p['name']), p['url'], p['prct']) for p in papers])
    body = body_base + body
    edit_post(reddit_api, post_id, body)
    # last_reddit_update = now
