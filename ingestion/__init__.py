"""WHAT THIS FOLDER IS
This folder builds Navi's knowledge from the official documents. It's run once, before Navi is used, and again whenever
the documents change. There are three steps:

    parse_docs.py     reads each document and splits it into sections and small searchable pieces.
    extract_graph.py  has an AI read each document and list its requirements and their order, then flags anything
                      suspicious so a person can check it.
    load_graph.py     loads the checked knowledge graph and the searchable pieces into the Neo4j database.
"""
