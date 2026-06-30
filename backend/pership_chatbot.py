from io import BytesIO
import streamlit as st # type: ignore
from manager_agent_01 import route_query
from rag_agent import RAGAgent
import os
import re
import json
from groq import Groq # type: ignore
from pathlib import Path
from scipy.io.wavfile import write as write_wav # type: ignore

from vector_db_create import DocumentProcessor
# pyrefly: ignore [missing-import]
from pathvalidate import sanitize_filename
import sounddevice as sd # type: ignore

WHISPER_MODEL = "base"  # Use 'tiny' for low-power devices
OLLAMA_MODEL = "smollm2:360m-instruct-q6_K"  # 1B parameter quantized model
BARK_VOICE = "v2/en_speaker_1"  # Simpler voice profile
SAMPLE_RATE = 16000  # Audio sample rate
RECORD_SECONDS = 10  # Recording duration



from dotenv import load_dotenv
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    try:
        config_data = json.load(open(f"config.json"))
        GROQ_API_KEY = config_data["GROQ_API_KEY"]
    except Exception:
        raise ValueError("GROQ_API_KEY must be defined in .env or config.json")
os.environ["GROQ_API_KEY"] = GROQ_API_KEY
client = Groq(api_key=GROQ_API_KEY)

st.set_page_config(
    page_title="Assistant.",
    page_icon="🧩",
    layout="centered"
)

st.title("🧠 Pership.ai 🤖")
st.markdown("The Talent Harmony System - Your assistant to enhance talent management.")
st.sidebar.markdown("# Chat with Pership.ai 🤖")

models = client.models.list()

for m in models.data:
    print(m.id)


def save_uploaded_file(uploaded_file):
        try:
            # Sanitize filename
            safe_name = sanitize_filename(uploaded_file.name)
            save_path = os.path.join(UPLOADS_DIR, safe_name)
            
            # Check for existing file
            if os.path.exists(save_path):
                base, ext = os.path.splitext(safe_name)
                counter = 1
                while os.path.exists(f"{base}_{counter}{ext}"):
                    counter += 1
                save_path = os.path.join(UPLOADS_DIR, f"{base}_{counter}{ext}")
            
            # Save file
            with open(save_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            return save_path
        except Exception as e:
            st.error(f"Error saving file: {e}")
            return None
# if 'available_docs' not in st.session_state:
#     st.session_state.available_docs = "{}"
if os.path.exists("FAISS_Index/processed_files.json"):
    with open("FAISS_Index/processed_files.json", "r") as f:
        processed_log = json.load(f)
        RAG_docs = {item["filename"] for item in processed_log}

    st.session_state.available_docs = str(RAG_docs)
else:     st.session_state.available_docs = {}

if "processor" not in st.session_state:
    st.session_state.processor = DocumentProcessor()    

RAG_Agent_response = RAGAgent().RAG_Agent_response  # type: ignore

with st.sidebar:
    with st.expander("ℹ️ About", expanded=False):
        for m in models.data:
            print(m.id)
            st.write(f"**Available Model**: `{m.id}`")

    st.header("Settings")
    model_choice = st.selectbox(
        "Manager Agent Model",
        ["gemma2-9b-it","llama-3.3-70b-versatile"],
        index=0
    )
    LLM_response_model = st.selectbox(
        "LLM Response Model",
        ["gemma2-9b-it","llama-3.3-70b-versatile"],
        index=0
    )
    UPLOADS_DIR = "uploaded_docs"
    os.makedirs(UPLOADS_DIR, exist_ok=True)
   
    temperature = st.slider("Temperature", 0.0, 1.0, 0.0, 0.1)
    st.markdown("---")
    summary = ''
    with st.expander("## RAG ⚙️ Configuration"):
        uploaded_file = st.file_uploader("Upload PDF", type=["pdf"],accept_multiple_files=False)
        summary = st.text_area("Summary About Uploaded Document (optional)", 
                               max_chars=100, 
                               height= 68,
                               help="Write a short summary about the document (optional).This will help the AI understand the context better and choose a Agent for you.")
        process_button = st.button("📄 Process Document ⚙️",use_container_width =True)
        if process_button:
            doc_summary = summary.strip()
            
            if uploaded_file:
                save_pdf_path = save_uploaded_file(uploaded_file) #os.path.join(os.getcwd(), uploaded_file.name)
                print("ABS path",save_pdf_path)
                if not st.session_state.processor.is_file_processed(save_pdf_path):
                    with st.spinner("🪡 Processing document..."):
                        buffer = BytesIO(uploaded_file.getbuffer())
                        if st.session_state.processor.process_pdf_from_buffer(buffer, uploaded_file.name,summary=doc_summary):
                            st.success("Document processed. 🎯")
                        else:
                            st.error("🛑 Processing failed.🛑")
                else:
                        st.info("Document 📄 already processed. 📚")   

        st.markdown("### Available Documents 📖")
        docz= ''
        print(type(st.session_state.available_docs))
        for doc in st.session_state.available_docs.split(", "):
            for doc in doc.strip("{").strip("}").strip("'").split("'"):
                docz = docz + f"\n- 📄 {doc}"
        # print(docz)
        # with st.expander('📚 Available Documents 📚'):
        st.info(f"{docz}")
            # print(f"Document: {doc}")
            
    st.markdown("---")


def load_chat_history():
    # Display chat messages
    st.empty()  # Clear previous messages
    for message in st.session_state.messages:
        print(message)
        
        if message["role"] == "user":
            with st.chat_message(message["role"],avatar="user"):
                st.markdown(f"{message['content']}")
            
        if message["role"] == "Manager Agent":
            with st.chat_message(message["role"],avatar="ai"):  
                # st.markdown(f"{message['content']}")
                #print(message)
                if message['selected_agent']:
                    with st.expander("💡 Manager Agent's Reasoning"):
                        if message['selected_agent'] != "None":
                            st.markdown(f"**➡️ Route To**: `{message['selected_agent']}`")
                            st.info(f"**🧙‍♂️ Reason**: {message['reason']}")
                        else:
                            st.info(f"**🧙‍♂️ Reason**: {message['reason']}")
                try:
                    if message['answer'] != 'No answer provided by the agent.':
                        st.success(f"{message['answer']}")
                except:
                    print("No Answer.")

        if message["role"] == "RAG_Agent":
            with st.chat_message(message["role"],avatar="🗄️"):
                
                if message["content"]:
                    st.markdown(f"{message["content"]}")
                with st.expander("📄 Document Sources"):    
                    if message["sources"]:
                        st.success(f"{message['sources']}")
                with st.expander("📝 Document Summary"):        
                    if message["summary doc"]:
                        st.info(f"{message["summary doc"]}")
        
    return True
def Manager_AG(response,Agent_none):
    # print("Response from Manager Agent:", response)
    Agent_none = Agent_none
    Manager_Agent_answer = response["answer"]
    # try:
        # Manager_Agent_answer = response["answer"]
        # Agent_none = True
        
    # except KeyError:
        # Manager_Agent_answer = "No answer provided by the agent."
        # Agent_none = False

    # Format the agent's response
    if response["selected_agent"] == "None":
        answer = f"**Manager Agent**: {response.get('answer', 'No agent selected.')}"
        Text_for_speech = response.get('answer', 'No agent selected.')       

    else:
        answer = f"**Route to**: `{response['selected_agent']}`\n\n**Reason**: {response['reason']}"
    
    # Display assistant response
    with st.chat_message("Manager Agent",avatar="ai"):
        with st.expander("💡 Manager Agent's Reasoning"):
            if response["selected_agent"] != "None":
                st.markdown(f"**➡️ Route To**: `{response['selected_agent']}`")
                st.info(f"**🧙‍♂️ Reason**: {response['reason']}")
            else:
                st.info(f"**🧙‍♂️ Reason**: {response['reason']}")                
                        
        st.markdown(answer)
        
    st.session_state.messages.append({"role": "Manager Agent", "content": answer, 
                                        "selected_agent": response["selected_agent"],
                                        "reason": response["reason"],
                                        "answer": Manager_Agent_answer
                                      })
    st.empty()  # Clear previous messages                                  
    # is_update_messages = load_chat_history()

    if not Agent_none:
        selected_agent = response["selected_agent"]
        if selected_agent == "RAG_Agent":
            RAG_Response,doc_sources = RAG_Agent_response(user_query,avalible_docs= st.session_state.available_docs , previous_messages="")
            print("\n ---------------------------- \n",RAG_Response)
            st.session_state.messages.append({"role": "RAG_Agent", "content": RAG_Response['Answer'],
                                        "summary doc": RAG_Response['summary'],
                                        "sources": doc_sources
                                      })
            
            Text_for_speech = RAG_Response['Answer']
            with st.spinner("Processing document..."):
                st.success(RAG_Response['Answer'])
                with st.expander("📄 Document Sources"):    
                    st.info(f"{doc_sources}")
                with st.expander("📝 Document Summary"):        
                    st.info(f"{RAG_Response['summary']}")

            # add_rag_response = load_chat_history()
        else:
            st.warning("No valid agent selected. Please try again.")
            Text_for_speech = 'No valid agent selected. Please try again.'
    return Text_for_speech

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []
else:
    # Load chat history from session state
    # st.session_state.messages = st.session_state.get("messages", [])
    is_load_messages = load_chat_history() # type: ignore


def record_audio():
    """Record audio from microphone"""
    print("\nSpeak now... (Recording for", RECORD_SECONDS, "seconds)")
    audio = sd.rec(int(RECORD_SECONDS * SAMPLE_RATE), 
                  samplerate=SAMPLE_RATE, 
                  channels=1, 
                  dtype='float32')
    sd.wait()
    print("Recording complete.")
    
    audio_np = audio.flatten()
    temp_file = str(Path("Voice_ai_log/temp_recording.wav"))  # Convert to string
    # write(temp_file, SAMPLE_RATE, audio_np)  # Using scipy.io.wavfile.write
    write_wav(temp_file, SAMPLE_RATE, audio_np)

def voice_for_text():
    try: 
        filename = str(Path("Voice_ai_log/temp_recording.wav"))  # Convert to string
        
        with open(filename, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(filename, file.read()),
                model="whisper-large-v3",
                response_format="verbose_json",
            )
            print("===========Text============\n", transcription.text,"\n =============\n")
            return transcription.text
    except Exception as e:
        print(f"Error generating speech: {e}")
        return None

def text_to_speech(text, language='en'):
    Ai_speech = text.strip()
    # Clean up the text for speech
    Ai_speech = re.sub(r'\\[tn]', ' ', Ai_speech)
    Ai_speech = re.sub(r'\\+', '', Ai_speech)
    Ai_speech = re.sub(r'[\_]', ' ', Ai_speech)
    Ai_speech = re.sub(r'[\*]', '', Ai_speech)
    Ai_speech = re.sub(r'\s+', ' ', Ai_speech).strip()
    
    speech_file_path = Path("Voice_ai_log/speech.wav")
    # Create the directory if it doesn't exist
    speech_file_path.parent.mkdir(exist_ok=True, parents=True)
                
    try:
        with st.spinner("Generating speech..."):
            with st.expander("Voice Pership ai"):
                
                # Generate the speech
                response = client.audio.speech.create(
                    model="canopylabs/orpheus-v1-english",
                    voice="troy",
                    input=Ai_speech,
                    response_format="wav",
                )
                print("Aiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiij")
                # Save the audio to file
                with open(speech_file_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=4096):
                        if chunk:
                            f.write(chunk)
                
                st.session_state.generated_audio = str(speech_file_path)
                st.success("Speech generated successfully!")
                
                # Play audio if generated
                if "generated_audio" in st.session_state:
                    st.audio(
                        st.session_state.generated_audio,
                        format="audio/wav",
                        start_time=0,
                        autoplay=True,
                        loop=False
                    )
    except Exception as e:
        st.error(f"Error generating speech: {e}")
        print(f"Error generating speech: {e}")



# User input
if user_query := st.chat_input("Ask a question..."):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)
    
    # Get agent routing response
    response,Agent_none = route_query(user_query)
    print(type(response))
    Manager_AG(response,Agent_none)

# with extra_col2:
if st.button("🗣️ Speak 🗣️"):
    # Check if the text to speech is available
    print("=== Offline Voice Assistant ===")
    with st.spinner("🎤 Voice Assistant Response..🤖"):
        st.info("🎤 Recording audio for 10 seconds...🎤")
        
        audio_data = record_audio()
        st.success("Recording complete.")
        # 2. Transcribe audio
        text_of_audio = voice_for_text()

        # transcription = transcribe_audio(audio_data)
        # print("Transcription:", transcription)
        with st.chat_message("user", avatar="user"):
            st.success(text_of_audio)
        st.session_state.messages.append({"role": "user", "content": text_of_audio})

        voice_response,Agent_none = route_query(text_of_audio)
        man_respo = Manager_AG(voice_response,Agent_none)
        text_to_speech(man_respo)
    
    
# Clear conversation history
st.sidebar.markdown("### Clear conversation history")
if st.sidebar.button("🗑️ Clear Chat History"):
    try:
        print("🛑 Ollama model stopped successfully.")
    except Exception as e:
        print(f"Could not stop Ollama model: {e}")
    st.session_state.assistant_conversation = []
    st.session_state.messages = []
    # print(st.session_state.chat_history)
    # os.system('cls' if os.name == 'nt' else 'clear')
    st.rerun()

# with extra_col2:
# if st.button("🗣️ Speak 🗣️"):
#     # Check if the text to speech is available
#     print("=== Offline Voice Assistant ===")
#     with st.spinner("🎤 Voice Assistant Response..🤖"):
#         st.info("🎤 Recording audio for 10 seconds...🎤")
        
#         audio_data = record_audio()
#         st.success("Recording complete.")
#         # 2. Transcribe audio
#         text_of_audio = voice_for_text()

#         # transcription = transcribe_audio(audio_data)
#         # print("Transcription:", transcription)
#         with st.chat_message("user", avatar="user"):
#             st.success(text_of_audio)
#         st.session_state.messages.append({"role": "user", "content": text_of_audio})

#         voice_response,Agent_none = route_query(text_of_audio)
#         man_respo = Manager_AG(voice_response,Agent_none)
#         text_to_speech(man_respo)


