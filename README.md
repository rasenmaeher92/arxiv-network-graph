
# MLG - Visual Machine Learning arxiv Graph and Textual explorer

MLG is a visual representation of ML researchers and papers from arXiv from the last year (for now). 
Each node in the graph is an authors and the edges represent co-authorship of papers.

MLG allows you to:
1. Search for papers or authors.
2. Filter by topics (NLP, Vision, etc).
3. Focus on specific author and explore his/her neighbors gradually.

![user interface](https://raw.github.com/ranihorev/arxiv-network-graph/master/arxiv_graph.jpeg)

The backend is based on arxiv-sanity but with a lot of modifications - all arXiv data is stored on MongoDB, rebuilt Twitter deamon, etc.

There are two large parts of the code:

1. / - arXiv text explorer 
2. /network - arXiv visual graph explorer 

### Dependencies  

```bash
$ virtualenv env                # optional: use virtualenv
$ source env/bin/activate       # optional: use virtualenv
$ pip install -r requirements.txt
```

There is still some legacy code from arxiv-sanity, therefore some of the

### Processing pipeline

1. Install and start MongoDB
2. Optional - Run `fetch_papers.py` to collect all paper from arXiv 
3. Create `twitter.txt` with your Twitter API credentials (values of consumer key and secret, in separate lines).
3. Run the flask server with `serve.py`. Visit localhost:5000 and enjoy sane viewing of papers!
4. Background tasks will to fetch new papers and search for twitter mentions

### Generating the network graph

After fetching papers from arXiv you can build the network graph by running the notebook `graph_generator.ipynb`.
It will overwrite the `static/network_data.json`. 

Note: Calculating the physics of the network (nodes' position) is very slow. The current hack is to run it once (by changing the physics settings in `network.js`) and store the calculated positions. I tried using networkX to calculate the positions, however, the results weren't pleasing...  

### Running online

If you'd like to run the flask server online (e.g. AWS) run it as `python serve.py --prod`.

You also want to create a `secret_key.txt` file and fill it with random text (see top of `serve.py`).