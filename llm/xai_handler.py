from .base import BaseLLM
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from openai import OpenAI
import json
import logging
import base64

from langchain_openai import ChatOpenAI
from langchain_core.utils.function_calling import convert_to_openai_function
from langchain_core.prompts import ChatPromptTemplate

from utils.prompt import *

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class IntentResponse(BaseModel):
    intent: str = Field(description="Identified intent of the user's message.")
    confidence: str = Field(description="Confidence of the indentified intent based on user message (High/Medium/Low)")
    reason: str = Field(description="Brief explanation for the classification based on the user message and conversation history.")

class CheckRelevanceResponse(BaseModel):
    document_type: str = Field(description="Identified type of the document based on the content.")
    confidence: str = Field(description="Confidence of the indentified type based on the content (High/Medium/Low)")

class ChatResponse(BaseModel):
    response: str = Field(description="The response generated for the user based on their input, providing relevant information or assistance.")
    chat_title: str = Field(description="A short title less than 4 words for the conversation")
    
class ContactInformation(BaseModel):
    person: str = Field(description="Name of the contact person for the loan-related queries.", default="MISSING")
    address: str = Field(description="Physical address of the company or branch offering the loan services.", default="MISSING")
    phone_number: str = Field(description="Contact phone number for loan inquiries.", default="MISSING")
    website: str = Field(description="Official website of the company providing the loan.", default="MISSING")
    email: str = Field(description="Email address for correspondence regarding loan services.", default="MISSING")

class DataFromDoc(BaseModel):
    company_name: str = Field(description="Name of the company providing the loan services.", default="MISSING")
    loan_plans: str = Field(description="Details of the loan plans offered.", default="MISSING")
    service_area: str = Field(description="Geographical regions where the company provides its loan services.", default="MISSING")
    credit_score_requirements: str = Field(description="Minimum credit score required to qualify for the loan.", default="MISSING")
    loan_minimum_amount: float = Field(description="The minimum loan amount that can be availed. Convert it into float value", default=0)
    loan_maximum_amount: float = Field(description="The maximum loan amount that can be availed. Convert it into float value", default=0)
    loan_to_value_ratio: float = Field(description="Loan-to-Value (LTV) ratio, typically expressed as a percentage. Convert it into float value", default=0)
    application_requirements: str = Field(description="List of documents or criteria required to apply for the loan.", default="MISSING")
    guidelines: str = Field(description="Guidelines and instructions related to the loan application process.", default="MISSING")
    contact_information: ContactInformation = Field(description="Details for contacting the company, including name, phone, address and email.", default="MISSING")
    property_types: str = Field(description="Types of properties eligible for loans, such as residential, commercial, etc.", default="MISSING")
    interest_rates: str = Field(description="Details about the interest rates applicable to the loan.", default="MISSING")
    points_charged: str = Field(description="Points or fees charged on the loan, often expressed as a percentage of the loan amount.", default="MISSING")
    liquidity_requirements: str = Field(description="Minimum liquidity required by the borrower to qualify for the loan.", default="MISSING")
    loan_to_cost_ratio: float = Field(description="Loan-to-Cost (LTC) ratio, typically expressed as a percentage. Convert it into float value", default=0)
    debt_service_coverage_ratio: float = Field(description="Debt Service Coverage Ratio (DSCR), representing the minimum income to cover debt obligations. Convert it into float value", default=0)
    loan_term: str = Field(description="Duration of the loan, usually expressed in months or years.", default="MISSING")
    amortization: str = Field(description="Details of the amortization schedule, specifying how the loan will be repaid.", default="MISSING")
    construction: str = Field(description="Indicates whether the loan is applicable for construction projects (yes/no).", default="MISSING")
    value_add: str = Field(description="Indicates whether the loan is applicable for value-add projects (yes/no).", default="MISSING")
    personal_guarantee: str = Field(description="Specifies if a personal guarantee is required for the loan (yes/no/partial).", default="MISSING")

class ExtractDocInfoResponse(BaseModel):
    extracted_info: DataFromDoc = Field(description="Data extracted from Loan document")
    message: str = Field(description="Generated User message")
    consent: bool = Field(default=False)
    is_updated: bool = Field(default=False)
    chat_title: str = Field(description="A short title less than 4 words for the document")

class FilterInformation(BaseModel):
    field: str = Field(description="Field to filter (e.g., name, service_area) mentioned in user message")
    operator: str = Field(description="Operator (e.g., '=', 'contains', 'startswith', 'textsearch').")
    value:  str = Field(description="Value or pattern for the filter.")

class ExtractFeatureResponse(BaseModel):
    filters: List[FilterInformation] = Field(description="List of all responsible filters extracted from user's message")

class XAIHandler(BaseLLM):
    def __init__(self, api_key: str):
        self.client = ChatOpenAI(
            model="grok-beta", 
            temperature=0, 
            timeout=None, 
            max_retries=3, 
            max_tokens=None, 
            base_url="https://api.x.ai/v1", 
            api_key=api_key,
            )
        self.logger = logging.getLogger(__name__)

    async def generate_response(self, intent, conversation_str, kb_result_str):
        try:
            prompt = ChatPromptTemplate.from_messages([("system", general_leading_prompt)])
            response = { "response": "" }

            if intent == 'specific_lender' or intent == 'filtered_lender_list':
                prompt = ChatPromptTemplate.from_messages([("system", specified_lender_prompt)])
                chain = prompt | self.client.with_structured_output(ChatResponse)
                response = chain.invoke({ "conversation": conversation_str, "relevant_lenders": kb_result_str })

            elif intent == "need_requirements":
                prompt = ChatPromptTemplate.from_messages([("system", need_requirement_prompt)])
                chain = prompt | self.client.with_structured_output(ChatResponse)
                response = chain.invoke({ "conversation": conversation_str })

            elif intent == "follow_up_lender":
                prompt = ChatPromptTemplate.from_messages([("system", follow_up_lender_prompt)])
                chain = prompt | self.client.with_structured_output(ChatResponse)
                response = chain.invoke({ "conversation": conversation_str })

            else: 
                chain = prompt | self.client.with_structured_output(ChatResponse)
                response = chain.invoke({ "conversation": conversation_str })

            return response

        except Exception as e:
            print(f"Error generating response: {e}")
            return type('Response', (object,), {
                "response": "I'm sorry, I couldn't generate a response. Please try again.",
                "chat_title": ""
            })()
    
    async def analyze_intent(self, message: str, conversation: list):
        try:
            recent_messages = conversation[-4:] if conversation else []
            recent_messages_str = ""

            if conversation and len(conversation):
                recent_messages_str = "\n".join(f"{msg['role']}: {str(msg['content'])}" for msg in recent_messages)

            prompt = ChatPromptTemplate.from_messages([("system", intent_anlyse_prompt)])
            chain = prompt | self.client.with_structured_output(IntentResponse)
            response = chain.invoke({"conversation_history": recent_messages_str, "user_message": message})
                    
            return response

        except Exception as e:
            self.logger.error(f"Error analyzing intent: {e}")
            return "other"

    def extract_document_info(self, text: str) -> Dict[str, str]:
        try:
            prompt = ChatPromptTemplate.from_messages([("system", extract_document_info_prompt)])
            chain = prompt | self.client.with_structured_output(ExtractDocInfoResponse)
            response = chain.invoke({"document_content": text})
            return response

        except Exception as e:
            self.logger.error(f"Error extracting information from document: {e}")
            return {}

    def extract_document_info_from_conversation(self, prompt: str, conversation: List[Dict[str, str]], previous_info: Dict[str, str]) -> Dict[str, str]:
        try:
            # Format previous info as a readable string
            previous_info_str = json.dumps(previous_info, indent=2)
            conversation_str = ""

            # Add conversation history
            if conversation:
                conversation_str = "\n".join(f"{msg['role']}: {str(msg['content'])}" for msg in conversation)
            
            conversation_str += "\n user: " + str(prompt)

            prompt = ChatPromptTemplate.from_messages([("system", extract_info_from_conversation_prompt)])
            chain = prompt | self.client.with_structured_output(ExtractDocInfoResponse)
            response = chain.invoke({"previous_info": previous_info_str, "conversation": conversation_str})

            return response

        except Exception as e:
            self.logger.error(f"Error extracting information from conversation: {e}")
            return previous_info

    def extract_feature_from_conversation(self,  message: str, conversation: list):
        try:
            recent_messages = conversation[-4:] if conversation else []
            recent_messages_str = ""

            if conversation and len(conversation):
                recent_messages_str = "\n".join(f"{msg['role']}: {str(msg['content'])}" for msg in recent_messages)

            prompt = ChatPromptTemplate.from_messages([("system", extract_feature_from_conversation_prompt)])
            chain = prompt | self.client.with_structured_output(ExtractFeatureResponse)
            response = chain.invoke({"conversation_history": recent_messages_str, "user_message": message})
            response = response.model_dump()

            query = self._construct_mongo_query(response['filters'])

            ## To Do --> Use this query parameter to fetch relevant lenders from mongo datbase. 
            ## Return the relevant lenders in array format. If not lender found return empty array.

            return query

        except Exception as e:
            self.logger.error(f"Error extracting features from conversation: {e}")
            return "other"

    def check_relevance(self, text: str):
        try:
            prompt = ChatPromptTemplate.from_messages([("system", check_relevance_prompt)])
            chain = prompt | self.client.with_structured_output(CheckRelevanceResponse)
            response = chain.invoke({"document_content": text})
            return response.model_dump()

        except Exception as e:
            self.logger.error(f"Error extracting information from document: {e}")
            return {}

    def _construct_mongo_query(self, filters):
        query = {}
        for condition in filters:
            field = condition["field"]
            operator = condition["operator"]
            value = condition["value"]

            if operator == "=":
                query[field] = value
            elif operator == "contains":
                query[field] = {"$regex": value, "$options": "i"}  # Case-insensitive match
            elif operator == "startswith":
                query[field] = {"$regex": f"^{value}", "$options": "i"}  # Prefix match
            elif operator == "textsearch":
                query["$text"] = {"$search": value}  # Full-text search
                
            elif operator == ">":
                query[field] = {"$gt": float(value)}
            elif operator == "<":
                query[field] = {"$lt": float(value)}
            elif operator == ">=":
                query[field] = {"$gte": float(value)}
            elif operator == "<=":
                query[field] = {"$lte": float(value)}
            elif operator == "between":
                min_val, max_val = map(float, value.split(","))
                query[field] = {"$gte": min_val, "$lte": max_val}

        return query

class XAIVisionHandler:
    def __init__(self, api_key: str):
        self.client = OpenAI(
            base_url="https://api.x.ai/v1", 
            api_key=api_key,
        )
        self.logger = logging.getLogger(__name__)

    def ocr(self, image_path: str) -> str:
        base64_image = self._encode_image(image_path)
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": "high",
                        },
                    },
                    {
                        "type": "text",
                        "text": image_ocr_prompt,
                    },
                ],
            },
        ]
        ocr_content = self.client.chat.completions.create(
            model="grok-2-vision-1212",
            messages=messages,
            temperature=0.01,
        )
        return ocr_content.choices[0].message.content

    def _encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        return encoded_string