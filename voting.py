import datetime
import logging
import uuid

import pymongo

from flask import Blueprint, render_template, session, abort, jsonify, request, make_response

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


@voting_app.route(BASE_PATH)
def wayr():
    resp = make_response(render_template('wayr.html'))
    resp.set_cookie(VOTING_COOKIE, str(uuid.uuid4()))
    return resp


def papers_json(paper_votes, papers_data):
    global tot_votes
    papers = [{'name': p['title'], 'id': p['_id'], 'url': p['link'], 'prct': int(100 * paper_votes.get(p['_id'], 0) / tot_votes),
               'value': paper_votes.get(p['_id'], 0)} for p in papers_data]
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

    papers = list(db_papers.find({'$or': [{'_id': q}, {'$text': {'$search': q}}]}, {'score': {'$meta': "textScore"}}).limit(MAX_ITEMS))
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
    return jsonify({'message': 'Thanks for voting!'})

