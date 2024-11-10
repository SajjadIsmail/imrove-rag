import os
import json
import uuid
import hashlib
import redis
from openai import OpenAI
from langchain_openai.embeddings import OpenAIEmbeddings
import pytesseract
from pdf2image import convert_from_path
from dotenv import load_dotenv
from pinecone import Pinecone
from langchain_pinecone import PineconeVectorStore

def extract_text_from_pdf(pdf_path):
    pages = convert_from_path(pdf_path, 300)
    text = ""
    for page_num, page in enumerate(pages):
        page_text = pytesseract.image_to_string(page)
        text += f"\nPage {page_num + 1}:\n{page_text}\n"
    return text

# Load environment variables
load_dotenv()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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

# Initialize Pinecone and Redis
pinecone_api_key = os.getenv("PINECONE_API_KEY")
pc = Pinecone(api_key=pinecone_api_key)
index = pc.Index('sample')
r = redis.Redis(host="localhost", port=6379)

# Path to the PDF file
pdf_path = r"D:\Lendordoc1.pdf"
extracted_text = extract_text_from_pdf(pdf_path)

# Get completion and function parameters
completion = client.chat.completions.create(
    model="gpt-4-0613",
    messages=[{"role": "user", "content": extracted_text}],
    functions=function_descriptions,
    function_call="auto",
)

# Check if the function call and arguments are present in the response
output = completion.choices[0].message
if output.function_call and output.function_call.arguments:
    params = json.loads(output.function_call.arguments)
else:
    print("Function call did not return arguments. Please check the function setup or input data.")
    params = None

if params:
    # Generate embeddings
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    vector = embeddings.embed_query(str(params))
    # Generate or get session ID
    session_id = input("Enter Details") or str(uuid.uuid4())
    # Create a unique hash for all parameters to check for exact duplicates
    params_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    # Use the company name as a key for partial match checks
    company_key = f"company:{params['Name Of The Company']}"
    # Check if an exact match exists
    if r.exists(params_hash):
        print("Exact duplicate entry detected. Skipping insertion.")
    elif r.exists(company_key):
        # Partial match: Check if any details differ from the existing entry
        existing_params = json.loads(r.hget(company_key, "params"))
        if existing_params != params:
            # Retrieve the existing session_id for the company
            existing_session_id = r.hget(company_key, "session_id").decode()
            # Update the existing document in Pinecone with the existing session_id
            index.upsert(
                vectors=[
                    {
                        "id": existing_session_id,
                        "values": vector,
                        "metadata": params
                    },
                ]
            )
            # Update Redis with new details for the existing company entry
            r.hset(company_key, "session_id", existing_session_id)
            r.hset(company_key, "params", json.dumps(params))
            print("Partial match found. Document updated with new details.")
        else:
            print("Entry is an exact duplicate. Skipping insertion.")
    else:
        # No match: Insert as a new entry
        index.upsert(
            vectors=[
                {
                    "id": session_id,
                    "values": vector,
                    "metadata": params
                },
            ]
        )
        # Use individual field updates for hset compatibility
        r.hset(company_key, "session_id", session_id)
        r.hset(company_key, "params", json.dumps(params))
        r.set(params_hash, session_id)  # Store the unique hash for exact duplicate checking
        print("New data inserted successfully.")
else:
    print("No valid parameters were returned from the function call.")