import logging

import schedule
import time
from fetch_papers import fetch_papers_main
from twitter_daemon import main_twitter_fetcher
from fetch_citations_and_references import update_all_papers

from logger import logger_config

if __name__ == '__main__':
    logger_config(info_filename='background_tasks.log')
    logger = logging.getLogger(__name__)

    logger.info('Start background tasks')

    schedule.every(30).minutes.do(main_twitter_fetcher)
    schedule.every(2).hours.do(fetch_papers_main)
    schedule.every().saturday.at("00:10").do(update_all_papers)

    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error(f'Major Error - {e}')
        time.sleep(1)