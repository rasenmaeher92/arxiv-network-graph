import logging
import threading

import schedule
import time
from fetch_papers import fetch_papers_main
from twitter_daemon import main_twitter_fetcher
from fetch_citations_and_references import update_all_papers

from logger import logger_config

def run_threaded(job_func):
    job_thread = threading.Thread(target=job_func)
    job_thread.start()

if __name__ == '__main__':
    logger_config(info_filename='background_tasks.log')
    logger = logging.getLogger(__name__)

    logger.info('Start background tasks')

    # schedule.every(30).minutes.do(run_threaded, main_twitter_fetcher)
    schedule.every(3).hours.do(run_threaded, fetch_papers_main)
    schedule.every().saturday.at("00:10").do(run_threaded, update_all_papers)

    while True:
        schedule.run_pending()
        time.sleep(1)