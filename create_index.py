import pymongo

if __name__ == '__main__':
    client = pymongo.MongoClient()
    mdb = client.arxiv
    papers = mdb.papers
    sem_sch_papers = mdb.sem_sch_papers

    res = papers.create_index(
        [
            ('title', 'text'),
            ('authors.name', 'text'),
            ('summary', 'text'),
            ('tags.term', 'text')
        ],
        weights={
            'title': 10,
            'authors.name': 5,
            'summary': 5,
            'tags.term': 5,
        }
    )

    res = sem_sch_papers.create_index(
        [
            ('title', 'text'),
        ],
    )