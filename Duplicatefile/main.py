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
pdf_path = r"D:\Doc1.pdf"
extracted_text = extract_text_from_pdf(pdf_path)

def is_complete(params):
    """Check if all required params are complete (no N/A, None, or empty fields)."""
    return all(value not in [None, "N/A", ""] for value in params.values())

# Get completion and function parameters
completion = client.chat.completions.create(
    model="gpt-4-0613",
    messages=[{"role": "system", "content":"If the information is not provided then fill is as N/A"},
        {"role": "user", "content": extracted_text}],
    functions=function_descriptions,
    function_call="auto",
)

# Check if the function call and arguments are present in the response
output = completion.choices[0].message
print(output)
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
    session_id = input("Enter Input:")
    if session_id:
        i = index.fetch(ids=[session_id])
        vector = i['vectors'][session_id]['metadata']
        print("Current Data In the knowledge base:", vector)
        changes = input("Enter the changes in the doc ")
        completion = client.chat.completions.create(
            model="gpt-4-0613",
            temperature=0,
            messages=[
                {"role": "system", "content": "You have to make the necessary changes in the content given by the user"
                                              "Only if the request to change name tell them the access is denied"
                                              "Format the response in json "}
                , {"role": "user", "content": f"{changes}\n\n{vector}"}],
            functions=function_descriptions,
            function_call="auto"
        )
        output = completion.choices[0].message.content
        print("Completion", output)
        print(type(output))
        if 'denied' in output.lower():
            print("Access Denied is present in the message.")
        else:
            data_dict = json.loads(output)  # Corrected to use json.loads() instead of json.dump()
            company_key = data_dict.get("Name Of The Company")
            print(company_key)
            existing_params = r.hget(company_key, "params")
            print(existing_params)
            if existing_params != output:
                r.hset(company_key, "session_id", session_id)
                r.hset(company_key, "params", output)
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
    if not session_id:
        session_id = str(uuid.uuid4())
        # Create a unique hash for all parameters to check for exact duplicates
        params_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        # Use the company name as a key for partial match checks
        company_key = f"{params['Name Of The Company']}"
        # Check if an exact match exists
        if r.exists(params_hash):
            print("Exact duplicate entry detected. Skipping insertion.")
        elif r.exists(company_key):
            # Partial match: Check if any details differ from the existing entry
            existing_params = json.loads(r.hget(company_key, "params"))
            if existing_params != params:
                # Retrieve the existing session_id for the company
                existing_session_id = r.hget(company_key, "session_id").decode()
                # Prepare a prompt for the model to describe the changes being made
                system_message = (
                    f"The existing parameters are: {existing_params}. "
                    f"The new parameters are: {params}. "
                    "Compare the both and tell the user these are the changes that are to be implemted based on the new paramters"
                    "Suppose if the parameter contain N/A then don't consider it and use the already existing values instead of it"
                    "Only give the update data"
                )

                completion = client.chat.completions.create(
                    model="gpt-4-0613",
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system_message},
                    ]
                )
                # Print the model's output, which should describe the necessary changes
                up = completion.choices[0].message.content
                print(completion.choices[0].message.content)
                rep = input("yes or No ")
                if rep == 'No':
                    print("No changes made")
                else:
                    completion = client.chat.completions.create(
                        model="gpt-4-0613",
                        temperature=0,
                        messages=[
                            {"role": "system",
                             "content": f"You have to make the necessary changes in the content given by the user and use {existing_params} as reference as it is the default document"
                                        "Only if the request to change name tell them the access is denied and don't change the name use the default name"
                                        "Format the response in json "}
                            , {"role": "user", "content": f"{rep}\n\n{up}"}],
                        functions=function_descriptions,
                        function_call="auto"
                    )
                    output = completion.choices[0].message.content
                    print("Completion", output)
                    print(type(output))
                    if 'denied' in output.lower():
                        print("Access Denied is present in the message.")
                    else:
                        data_dict = json.loads(output)
                        company_key = data_dict.get("Name Of The Company")
                        print(company_key)
                        existing_params = r.hget(company_key, "params")
                        print(existing_params)
                        if existing_params != output:
                            r.hset(company_key, "session_id", existing_session_id)
                            r.hset(company_key, "params", output)
                        update = json.loads(output)
                        print("JSON", update)
                        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
                        vector = embeddings.embed_query(json.dumps(update))
                        index.upsert(
                            vectors=[
                                {
                                    "id": existing_session_id,
                                    "values": vector,
                                    "metadata": update
                                },
                            ]
                        )
                print("Partial match found. Document updated with new details.")
                print("Session_ID: ",existing_session_id)
            else:
                print("Entry is an exact duplicate. Skipping insertion.")
                existing_session_id = r.hget(company_key, "session_id").decode()
                print("Session ID: ",existing_session_id)

        else:
            if is_complete(params):
                # No match: Insert as a new entry
                vector = embeddings.embed_query(str(params))
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
                print("Session_ID:",session_id)
            else:
                system_message = (
                    f"The parameters are: {params}."
                    "Check for the parameter which consist of N/A and ask details of it"
                )

                completion = client.chat.completions.create(
                    model="gpt-4-0613",
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system_message},
                    ]
                )
                # Print the model's output, which should describe the necessary changes
                up = completion.choices[0].message.content
                print(completion.choices[0].message.content)
                rep = input()
                completion = client.chat.completions.create(
                    model="gpt-4-0613",
                    temperature=0,
                    messages=[
                        {"role": "system",
                         "content": f"You have to make the necessary changes in the content given by the user and use {params} as reference as it is the default document"
                                    "Only if the request to change name tell them the access is denied and don't change the name use the default name"
                                    "Format the response in json "}
                        , {"role": "user", "content": f"{rep}"}],
                    functions=function_descriptions,
                    function_call="auto"
                )
                output = completion.choices[0].message.content
                print("Completion", output)

                params_hash = hashlib.sha256(json.dumps(output, sort_keys=True).encode()).hexdigest()
                params = json.loads(output)
                company_key = f"{params['Name Of The Company']}"
                vector = embeddings.embed_query(str(params))
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
                print("Session_ID:", session_id)
else:
    print("No valid parameters were returned from the function call.")