"""
Queries arxiv API and downloads papers (the query is a parameter).
The script is intended to enrich an existing database pickle (by default db.p),
so this file will be loaded first, and then new results will be added to it.
"""
import logging

import dateutil.parser
import pymongo
import time
import random
import argparse
import urllib.request
import feedparser

from logger import logger_config

logger = logging.getLogger(__name__)
BASE_URL = 'http://export.arxiv.org/api/query?' # base api query url

client = pymongo.MongoClient()
mdb = client.arxiv
papers = mdb.papers
authors = mdb.authors


def encode_feedparser_dict(d):
    """
    helper function to get rid of feedparser bs with a deep copy.
    I hate when libs wrap simple things in their own classes.
    """
    if isinstance(d, feedparser.FeedParserDict) or isinstance(d, dict):
        j = {}
        for k in d.keys():
            j[k] = encode_feedparser_dict(d[k])
        return j
    elif isinstance(d, list):
        l = []
        for k in d:
            l.append(encode_feedparser_dict(k))
        return l
    else:
        return d

def parse_arxiv_url(url):
    """
    examples is http://arxiv.org/abs/1512.08756v2
    we want to extract the raw id and the version
    """
    ix = url.rfind('/')
    idversion = url[ix+1:] # extract just the id (and the version)
    parts = idversion.split('v')
    assert len(parts) == 2, 'error parsing url ' + url
    return parts[0], int(parts[1])

def fetch_entries(query):
    with urllib.request.urlopen(BASE_URL + query) as url:
        response = url.read()
    parse = feedparser.parse(response)
    num_added = 0
    num_skipped = 0
    for e in parse.entries:

        j = encode_feedparser_dict(e)

        # extract just the raw arxiv id and version for this paper
        rawid, version = parse_arxiv_url(j['id'])
        j['_rawid'] = rawid
        j['_version'] = version

        # add to our database if we didn't have it before, or if this is a new version
        cur_id = {'_id': rawid}
        cur_paper = list(papers.find(cur_id))
        j['time_updated'] = dateutil.parser.parse(j['updated'])
        j['time_published'] = dateutil.parser.parse(j['published'])

        if not cur_paper or '_version' not in cur_paper[0] or j['_version'] > cur_paper[0]['_version']:
            papers.update(cur_id, {'$set': j}, True)
            num_added += 1
        else:
            num_skipped += 1

        if not cur_paper:
            for a in j['authors']:
                authors.update({'_id': a['name']}, {'$addToSet': {'papers': rawid}}, True)

    return num_added, num_skipped


DEF_QUERY = 'cat:cs.CV+OR+cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL+OR+cat:cs.NE+OR+cat:stat.ML'


def fetch_papers_main(start_index=0, max_index=3000, results_per_iteration=200, wait_time=5, search_query=DEF_QUERY, break_on_no_added=1):
    # main loop where we fetch the new results
    logger.info('Updating paper DB')
    for i in range(start_index, max_index, results_per_iteration):
        num_failures = 0

        logger.info("Results %i - %i" % (i, i + results_per_iteration))
        query = 'search_query=%s&sortBy=lastUpdatedDate&start=%i&max_results=%i' % (search_query, i, results_per_iteration)
        while num_failures < 10:
            num_added, num_skipped = fetch_entries(query)
            if num_added == 0 and num_skipped > 0 and break_on_no_added == 1:
                logger.info('No new papers were added. Assuming no new papers exist. Exiting.')
                return

            elif num_added + num_skipped > 0:
                logger.info('Added %d papers, already had %d.' % (num_added, num_skipped))
                break
            else:
                logger.info('Received no results from arxiv. Retrying after sleep')
                num_failures += 1
                time.sleep(5)
        # print some information

        logger.info(f'Sleeping for {wait_time} seconds')
        time.sleep(wait_time + random.uniform(0, 3))


if __name__ == "__main__":

    logger_config()
    # parse input arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--search-query', type=str,
                        default=DEF_QUERY,
                        help='query used for arxiv API. See http://arxiv.org/help/api/user-manual#detailed_examples')
    parser.add_argument('--start-index', type=int, default=0, help='0 = most recent API result')
    parser.add_argument('--max-index', type=int, default=3000, help='upper bound on paper index we will fetch')
    parser.add_argument('--results-per-iteration', type=int, default=200, help='passed to arxiv API')
    parser.add_argument('--wait-time', type=float, default=5.0, help='lets be gentle to arxiv API (in number of seconds)')
    parser.add_argument('--break-on-no-added', type=int, default=1, help='break out early if all returned query papers are already in db? 1=yes, 0=no')
    args = parser.parse_args()

    # misc hardcoded variables
    print('Searching arXiv for %s' % (args.search_query, ))

    fetch_papers_main(args.start_index, args.max_index, args.results_per_iteration, args.wait_time, args.search_query, args.break_on_no_added)