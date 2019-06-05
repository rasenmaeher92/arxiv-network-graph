
# Description

This fork of arxiv-sanity and arxiv network graph aims at creating a visual tool for the scientific paper writing process.
It should aid its users through the stages of literature research, topic determination and paper writing.
It does so by providing a graph-based way to explore papers and their authors.


# How to Use

To use this project run the following scripts:
1. `fetch_papers.py` to get the papers from arxiv.org
2. `fetch_citations_and_references.py` to get meta data from semanticscholar.org
3. `create_authors.py`
4. `create_index.py`
5. `run_background_tasks.py` to start background tasks scheduler. 
6. `serve.py` to start the flask server.
7. go to localhost:5000/citations_network

# (Planned) New Features

## Semantic Ordering
- use arxiv-sanity similarity scores code to introduce semantic edges in the graph
- 

## Filtering
- provide node filtering options to filter citations and references nodes
- filters for citations count, age, etc.
- combination options for above filters
-

## Usability
- introduce sidebar to control the following options
- tagging of papers and authors
- list papers and authors in side bar with all info
- user system to save seed papers and authors
- show pdf thumbnail in paper desc
- query google scholar image for authors
-

## Data Visualization
- use appearance, color and size of nodes to indicate citation count, age, etc. 
-



# (Planned) Bug Fixes
- sometimes edges have duplicates
- papers do not appear when magnicfication icon is pressed in description field

# (Planned) Architectural Changes
- move paper fetching to background of `serve.py`
- docker containrization? 
- unify branding
- remove/hid arxiv-sanity front facing part

(contributes welcome)

# Old readme below

# MLG - Visual Machine Learning arxiv Graph and Textual explorer

MLG (Machine Learning Graph) is a visual representation of ML researchers and papers, and the connections between them.
Each node in the graph (/citations_network) is an author or a paper, and an edge can represent a citation, a reference or a authorship. 

Note: There is an old version of the graph (/network) in which edges represent co-authorship of papers, based solely on arXiv.org.

Live demo is available at [Lyrn.ai](https://arxiv.lyrn.ai/citations_network). 

MLG allows you to:
1. Search for papers or authors.
2. Navigate between related papers and authors. 
3. Click on a node to view its list of papers and double click to expand its connections.
4. Re-organize the network after expanding. 

The backend is based on arxiv-sanity but with a lot of modifications:
* The papers data is collected from arxiv.org and semanticscholar.org. Everything is stored on MongoDB.
* Rebuilt the Twitter daemon - it now collects tweets from a list of prominent ML accounts, in addition for searching arxiv.org links on Twitter. 
   
The project includes three parts:

1. / - arXiv text explorer.
2. /citations_network - The new visual network graph explorer. 
3. /network - The old arXiv visual graph explorer.
  
![NewVersion](https://media.giphy.com/media/48OslMteQHE8krVVMu/giphy.gif)

Example of the old version: 

![user interface](https://raw.github.com/ranihorev/arxiv-network-graph/master/arxiv_graph.jpg)

### Dependencies  

```bash
$ virtualenv env                # optional: use virtualenv
$ source env/bin/activate       # optional: use virtualenv
$ pip install -r requirements.txt
```

There is still some legacy code from arxiv-sanity that require some of the packages in the requirement. 

### Processing pipeline

1. Install and start MongoDB
2. Optional - Run `fetch_papers.py` to collect all paper from arXiv. Run `fetch_citations_and_references.py` to collect data from semanticScholar.org.  
3. Create `twitter.txt` with your Twitter API credentials (values of consumer key and secret, in separate lines). You can also add accounts to the `twitter_users.json` file. 
3. Run `run_background_tasks.py` to start background tasks scheduler. 
4. Run the flask server with `serve.py`.

### Old version - Generating the network graph

After fetching papers from arXiv you can build the network graph by running the notebook `graph_generator.ipynb`.
It will overwrite the `static/network_data.json`. 

Note: Calculating the physics of the network (nodes' position) is very slow. The current hack is to run it once (by changing the physics settings in `network.js`) and store the calculated positions. I tried using networkX to calculate the positions, however, the results weren't pleasing...  

### Running online

If you'd like to run the flask server online (e.g. AWS) run it as `python serve.py --prod`.

You also want to create a `secret_key.txt` file and fill it with random text (see top of `serve.py`).