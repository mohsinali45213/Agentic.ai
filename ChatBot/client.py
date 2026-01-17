import streamlit as st
from server import chatbot,retrieve_all_threads,get_thread_title
from langchain_core.messages import HumanMessage,AIMessage
import uuid

st.set_page_config(page_title="ChatBot", page_icon="🤖")
st.title("🤖 ChatBot")



def generate_thread_id():
  id = uuid.uuid4()
  return id

def reset_chat():
  thread_id = generate_thread_id()
  st.session_state["chat_id"] = thread_id
  st.session_state["chat_history"] = []
  add_thread(st.session_state['chat_id'])

def add_thread(thread_id):
  if thread_id not in st.session_state["thread_list"]:
    st.session_state["thread_list"].append(thread_id)
    
def load_chats(thread_id):
  config = {"configurable":{"thread_id":thread_id}}
  chat = chatbot.get_state(config=config)
  return chat.values.get("messages",[])



if "chat_id" not in st.session_state:
  st.session_state["chat_id"] = generate_thread_id()
  
if "thread_list" not in st.session_state:
  st.session_state["thread_list"] = retrieve_all_threads()
  
if "chat_history" not in st.session_state:
  st.session_state["chat_history"] = []
  
if "title" not in st.session_state:
  st.session_state["title"] = "untitled"

add_thread(st.session_state["chat_id"])



st.sidebar.title("LangGraph Chatbot")
if st.sidebar.button("New"):
  reset_chat()
  
st.sidebar.header("Conversations")

for thread_id in st.session_state["thread_list"]:
  title = get_thread_title(thread_id)
  if st.sidebar.button(title, key=str(thread_id)):
    st.session_state["chat_id"] = thread_id
    st.session_state["chat_history"] = load_chats(thread_id)
    
  
for message in st.session_state['chat_history']:
    with st.chat_message("user" if isinstance(message,HumanMessage) else "assistant"):
      st.text(message.content)
        

user_input = st.chat_input('Type here')

if user_input:
    st.session_state['chat_history'].append(HumanMessage(content=user_input))
    with st.chat_message('user'):
        st.text(user_input)
        
    CONFIG = {'configurable': {'thread_id': st.session_state['chat_id']}}
    
    with st.chat_message("assistant"):
      def ai_only_stream():
        for message_chunk, metadata in chatbot.stream(
            {"messages": [HumanMessage(content=user_input)],"title":""},
            config=CONFIG,
            stream_mode="messages"
        ):
          st.write(message_chunk)
          if isinstance(message_chunk, AIMessage):
              # yield only assistant tokens
              yield message_chunk.content
      ai_message = st.write_stream(ai_only_stream())
      
      
    st.session_state['chat_history'].append(AIMessage(content=ai_message))
