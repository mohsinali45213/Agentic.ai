from langgraph.graph import StateGraph,START,END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import  BaseMessage,HumanMessage
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import  TypedDict,Annotated,Literal
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from dotenv import load_dotenv
import sqlite3
load_dotenv()

class ChatState(TypedDict):
  messages: Annotated[list[BaseMessage], add_messages]
  title: str
  
# model = ChatGoogleGenerativeAI(model="gemini-robotics-er-1.5-preview")
model = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite")

def chat_node(state: ChatState) -> ChatState:
  
  prompt = PromptTemplate(
      input_variables=["messages"],
      template="The following is a conversation between a human and an AI assistant. The assistant is helpful, creative, clever, and very friendly.\n\n{messages}\nAI:.do not use any markdown formatting in your response"
  )
  chain = prompt | model
  response = chain.invoke({"messages": state["messages"]})
  return {"messages": [response]} 

def create_title(state: ChatState):
  prompt = PromptTemplate(
      input_variables=["messages"],
      template="Create a 4 word title for the following conversation and do not include any extra information: {messages}.do not use any quotation marks in the title"
  )
  chain = prompt | model | StrOutputParser()
  title = chain.invoke({"messages": state["messages"]})
  return {"title": title}

def route(state: ChatState) -> Literal["create_title","__end__"]:
  if not state.get("title"):  # Safer check
    return "create_title"
  return END
  

graph = StateGraph(ChatState)

graph.add_node("chat_node",chat_node)
graph.add_node("create_title",create_title)
graph.add_edge(START,"chat_node")
graph.add_conditional_edges("chat_node",route)
graph.add_edge("create_title", END)

conn = sqlite3.connect(database="chatbot.db", check_same_thread=False)
checkpointer = SqliteSaver(conn=conn)

chatbot = graph.compile(checkpointer=checkpointer)


def retrieve_all_threads():
  all_threads = set()
  for checkpoint_tuple in checkpointer.list(None):
      thread_id = checkpoint_tuple.config['configurable']['thread_id']
      all_threads.add(thread_id)
  return list(all_threads)

def get_thread_title(thread_id):
  """Get the title for a specific thread"""
  config = {"configurable": {"thread_id": thread_id}}
  state = chatbot.get_state(config=config)
  return state.values.get("title", f"Chat {str(thread_id)[:8]}...")
