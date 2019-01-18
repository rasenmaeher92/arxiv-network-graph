import json
import logging
import praw

logger = logging.getLogger(__name__)


def create_reddit_api():
    try:
        with open('reddit_keys.json') as f:
            keys = json.load(f)
            return praw.Reddit(**keys)
    except Exception as e:
        logger.error('Failed to read reddit keys - {}'.format(e))

    return None


def edit_post(reddit_api, id, text):
    post = reddit_api.submission(id=id)
    try:
        post.edit(text)
    except Exception as e:
        logger.error('Failed to update post - {}'.format(e))