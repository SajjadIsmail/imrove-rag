import json
from pinecone import Pinecone
from openai import OpenAI
from dotenv import load_dotenv
import os
from langchain_openai.embeddings import OpenAIEmbeddings

load_dotenv()
pinecone_api_key = os.getenv("PINECONE_API_KEY")
pc = Pinecone(api_key=pinecone_api_key)
index = pc.Index('sample')

session_id = "1bd95bd6-04e2-4b86-9f96-ea08eb770352"

i = index.fetch(ids=[session_id])
vector = i['vectors'][session_id]['metadata']
print("Current Data In the knowledge base:",vector)

function_descriptions = [
    {
        "name": "get_doc_detail",
        "description": "Based on the given details fill all the parameters",
        "parameters": {
            "type": "object",
            "properties": {
                "Name Of The Company": {"type": "string", "description": "Company's Name"},
                "Loan Amount": {"type": "string", "description": "Money willing to lend"},
                "Loan Term": {"type": "string", "description": "Duration Of the amount"},
                "LTV": {"type": "string", "description": "Type of LTV"},
                "Fee": {"type": "string", "description": "Upfront fee for processing"},
                "Amortization": {"type": "string", "description": "Required tenure"},
            },
            "required": ["Name Of The Company", "Loan Amount", "Loan Term", "LTV", "Fee", "Amortization"],
        },
    },
]
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

changes = input("Enter the changes in the doc ")

completion = client.chat.completions.create(
    model="gpt-4-0613",
    temperature=0,
    messages=[{"role": "system", "content": "You have to make the necessary changes in the content given by the user"
                                            "Only if the request to change name tell them the access is denied"
                                            "Format the response in json "}
        ,{"role": "user", "content": f"{changes}\n\n{vector}"}],
    functions=function_descriptions,
    function_call="auto"
)

output = completion.choices[0].message.content

print("Completion",output)
if 'denied' in output.lower():
    print("Access Denied is present in the message.")
else:
    update = json.loads(output)
    print("JSON", update)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    vector = embeddings.embed_query(json.dumps(update))
    index.upsert(
        vectors=[
            {
                "id": session_id,
                "values": vector,
                "metadata": update
            },
        ]
    )
