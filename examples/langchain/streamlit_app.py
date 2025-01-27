import streamlit as st
import pandas as pd
import os
import re
import pickle
import jwt

from dotenv import load_dotenv
from langchain import OpenAI
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores.faiss import FAISS
from langchain.document_loaders import CubeSemanticLoader
from pathlib import Path

from utils import (
    create_docs_from_values,
    create_vectorstore,
    init_vectorstore,
    check_input,
    log,
    call_sql_api,
    CUBE_SQL_API_PROMPT,
    _NO_ANSWER_TEXT,
    PROMPT_POSTFIX,
)

load_dotenv()

def ingest_cube_meta():
    security_context = {}
    token = jwt.encode(security_context, os.environ["CUBE_API_SECRET"], algorithm="HS256")

    loader = CubeSemanticLoader(os.environ["CUBE_API_URL"], token)
    documents = loader.load()

    embeddings = OpenAIEmbeddings()
    vectorstore = FAISS.from_documents(documents, embeddings)

    # Save vectorstore
    with open("vectorstore.pkl", "wb") as f:
        pickle.dump(vectorstore, f)
        
if not Path("vectorstore.pkl").exists():
    with st.spinner('Loading context from Cube API...'):
        ingest_cube_meta();

llm = OpenAI(
    temperature=0, openai_api_key=os.environ.get("OPENAI_API_KEY"), verbose=True
)

st.title("Cube and LangChain demo 🤖🚀")

multi = '''
Follow [this tutorial on Github](https://github.com/cube-js/cube/tree/master/examples/langchain) to clone this project and run it locally. 

You can use these sample questions to quickly test the demo --
* How many orders?
* How many completed orders?
* What are top selling product categories?
* What product category drives the highest average order value?
'''
st.markdown(multi)

question = st.text_input(
    "Your question: ", placeholder="Ask me anything ...", key="input"
)

if st.button("Submit", type="primary"):
    check_input(question)
    vectorstore = init_vectorstore()

    # log("Quering vectorstore and building the prompt...")

    docs = vectorstore.similarity_search(question)
    # take the first document as the best guess
    table_name = docs[0].metadata["table_name"]

    # Columns
    columns_question = "All available columns"
    column_docs = vectorstore.similarity_search(
        columns_question, filter=dict(table_name=table_name), k=15
    )

    lines = []
    for column_doc in column_docs:
        column_title = column_doc.metadata["column_title"]
        column_name = column_doc.metadata["column_name"]
        column_data_type = column_doc.metadata["column_data_type"]
        print(column_name)
        lines.append(
            f"title: {column_title}, column name: {column_name}, datatype: {column_data_type}, member type: {column_doc.metadata['column_member_type']}"
        )
    columns = "\n\n".join(lines)

    # Construct the prompt
    prompt = CUBE_SQL_API_PROMPT.format(
        input_question=question,
        table_info=table_name,
        columns_info=columns,
        top_k=1000,
        no_answer_text=_NO_ANSWER_TEXT,
    )

    # Call LLM API to get the SQL query
    log("Calling LLM API to generate SQL query...")
    llm_answer = llm(prompt)
    bare_llm_answer = re.sub(r"(?i)Answer:\s*", "", llm_answer)

    if llm_answer.strip() == _NO_ANSWER_TEXT:
        st.stop()
        
    sql_query = llm_answer

    log("Query generated by LLM:")
    st.info(sql_query)

    # Call Cube SQL API
    log("Sending the above query to Cube...")
    columns, rows = call_sql_api(sql_query)

    # Display the result
    df = pd.DataFrame(rows, columns=columns)
    st.table(df)
