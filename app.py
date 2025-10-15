import streamlit as st
from openai import OpenAI
import google.generativeai as genai
from groq import Groq
import os, time, json5, tempfile, re, io, base64
from googleapiclient.discovery import build
from PIL import Image
from gtts import gTTS
import speech_recognition as sr
from pydub import AudioSegment

# --- Initialize clients ---
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", st.secrets.get("OPENAI_API_KEY")))
genai.configure(api_key=os.getenv("GEMINI_API_KEY", st.secrets.get("GEMINI_API_KEY")))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY", st.secrets.get("GROQ_API_KEY")))

# --------------- CONFIG ---------------
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.error("⚠️ OpenAI API key is missing. Set OPENAI_API_KEY as environment variable.")
openai = OpenAI(api_key=api_key)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "YOUR_KEY_HERE")

# --- Universal AI call ---
def ask_ai(prompt, max_tokens=600):
    """
    Try OpenAI first → fallback to Gemini → then Groq (Llama 3).
    Works even if one or more APIs are out of quota.
    """
    # Try OpenAI (primary)
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        error = str(e)
        if "insufficient_quota" in error or "rate_limit" in error:
            st.warning("⚠️ OpenAI quota reached — switching to free backup model...")
        else:
            st.warning(f"⚠️ OpenAI error: {e}")
    
    # Try Gemini (backup)
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        st.warning(f"⚠️ Gemini backup failed: {e}")

    # Try Groq (Llama 3, free tier)
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"❌ All AI services failed: {e}")
        return "AI service unavailable. Please try again later."

# --------------- UTILITIES ---------------
def ask_openai(prompt, max_tokens=600):
    if not api_key:
        return "OpenAI API key not set."
    profile = st.session_state.get("user_profile", {})
    profile_context = ""
    if profile:
        profile_context = f"The user is {profile.get('name','a student')} in grade {profile.get('grade','unknown')}, studying {profile.get('subjects','many subjects')} and wants {profile.get('goal','to learn better')}.\n\n"
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role":"system","content":"You are a friendly AI Study Buddy who explains concepts clearly."},
                {"role":"user","content": profile_context + prompt}
            ],
            max_tokens=max_tokens
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"OpenAI API error: {e}"

def speak_text(text):
    tts = gTTS(text)
    path = "tts.mp3"
    tts.save(path)
    return path

def generate_quiz(topic, n=5):
    prompt = (
        f"Create {n} multiple-choice questions about {topic}. "
        "Return ONLY valid JSON like this:\n"
        '{"questions":[{"question":"...","options":["A","B","C","D"],"answer_index":0}]}\n'
        "Do not include explanations or any extra text outside JSON."
    )
    try:
        raw = ask_openai(prompt)
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON found in response.")
        json_text = json_match.group(0)
        quiz_data = json5.loads(json_text)
        return quiz_data
    except Exception as e:
        st.error(f"⚠️ Quiz parse error: {e}")
        st.write("Raw model reply for debugging:", raw)
        return {"questions": []}

def youtube_search(q):
    if not YOUTUBE_API_KEY or YOUTUBE_API_KEY=="YOUR_KEY_HERE":
        st.warning("⚠️ YouTube API key not set.")
        return []
    try:
        yt = build("youtube","v3",developerKey=YOUTUBE_API_KEY)
        res = yt.search().list(q=q,part="snippet",maxResults=5,type="video").execute()
        vids=[]
        for i in res["items"]:
            vids.append({
                "title": i["snippet"]["title"],
                "url": f"https://www.youtube.com/watch?v={i['id']['videoId']}",
                "thumb": f"https://img.youtube.com/vi/{i['id']['videoId']}/0.jpg"
            })
        return vids
    except Exception as e:
        st.warning(f"YouTube API error: {e}")
        return []

# --------------- UI SETUP ---------------
st.set_page_config(page_title="AI Study Buddy", page_icon="🎓", layout="wide")
st.title("🎓 AI Study Buddy")

menu = st.sidebar.radio("Navigate",["👤 Profile","🧠 Explain Topic","📝 Quiz","📸 Scan Photo","💡 Flashcards","🎥 YouTube","🗒️ Notes","🎧 Voice Assistant"])

# --------------- PROFILE ---------------
if menu=="👤 Profile":
    st.header("👤 Your Learning Profile")
    name=st.text_input("Name")
    grade=st.text_input("Grade/Year")
    subjects=st.text_input("Subjects or Interests")
    goal=st.text_area("Learning Goal")
    if st.button("Save"):
        st.session_state["user_profile"]={"name":name,"grade":grade,"subjects":subjects,"goal":goal}
        st.success("Profile saved!")
    if "user_profile" in st.session_state: st.json(st.session_state["user_profile"])

# --------------- EXPLAIN TOPIC ---------------
elif menu=="🧠 Explain Topic":
    st.header("🧠 Explain Topic")
    topic=st.text_input("Enter a topic:")
    if st.button("Explain"):
        ans=ask_openai(f"Explain {topic} simply with examples.")
        st.write(ans)
        st.audio(speak_text(ans))

# --------------- QUIZ ---------------
elif menu=="📝 Quiz":
    st.header("📝 Quiz")
    topic=st.text_input("Topic for quiz:")
    n=st.slider("Number of questions",1,10,5)
    if st.button("Generate Quiz"):
        quiz=generate_quiz(topic,n)
        if not quiz["questions"]: st.error("Quiz generation failed.")
        else:
            st.session_state.quiz=quiz["questions"]
            st.success("Quiz ready!")
    if "quiz" in st.session_state:
        qlist=st.session_state.quiz
        for i,q in enumerate(qlist):
            st.markdown(f"**Q{i+1}. {q['question']}**")
            ans=st.radio("",q["options"],key=f"q{i}")
            if st.button(f"Check Q{i+1}",key=f"chk{i}"):
                correct=q["options"][q["answer_index"]]
                if ans==correct:
                    st.success("✅ Correct!")
                else:
                    st.error(f"❌ Correct answer: {correct}")
                    st.audio(speak_text(f"The correct answer is {correct}"))

# ----------------- SCAN PHOTO (with GPT-based OCR + Summarizer) -----------------
elif menu=="📸 Scan Photo":
    st.subheader("📸 Scan and Summarize Notes")

    up = st.file_uploader("Upload an image", type=["jpg", "jpeg", "png"])
    if up:
        # --- Load and preview image ---
        img = Image.open(up)
        st.image(img, caption="Uploaded Image", width=350)

        # --- Read image bytes ---
        img_bytes = up.read()

        # --- Compress if too large (>1 MB) ---
        if len(img_bytes) > 1_000_000:
            img = img.resize((800, int(800 * img.height / img.width)))
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            img_bytes = buffer.getvalue()

        # --- Convert to Base64 for GPT processing ---
        img_b64 = base64.b64encode(img_bytes).decode()

        # --- Prepare prompt ---
        prompt = f"""
        You are an AI assistant that extracts readable text from an image (OCR).
        Below is the image encoded in Base64. Extract all visible text clearly and accurately.
        Return only the extracted text — no explanations, no formatting, no markdown.

        Base64 image:
        {img_b64}
        """

        # --- Process image using GPT-3.5 (more affordable & stable) ---
        try:
            with st.spinner("🔍 Extracting text from image..."):
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are an AI that extracts and summarizes text from images."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=1500,
                )

            # --- Extracted text ---
            text = response.choices[0].message.content.strip()
            st.text_area("📝 Extracted Text:", text, height=180)

            # --- Summarization / Explanation ---
            if st.button("✨ Summarize / Explain"):
                with st.spinner("🧠 Summarizing the extracted content..."):
                    summary = ask_ai(f"Summarize or explain this text in simple terms:\n{text}")
                    st.write("### 📘 Summary / Explanation:")
                    st.write(summary)

                    # --- Optional: Audio output ---
                    st.audio(speak_text(summary))

        except Exception as e:
            st.error(f"⚠️ OpenAI API error: {e}")

# --------------- FLASHCARDS ---------------
elif menu=="💡 Flashcards":
    st.header("💡 Flashcards")
    topic=st.text_input("Topic:")
    n=st.slider("How many flashcards?",1,10,5)
    if st.button("Generate Flashcards"):
        cards=ask_ai(f"Create {n} flashcards to revise {topic}. Each should have a term and definition.")
        st.write(cards)

# --------------- YOUTUBE ---------------
elif menu=="🎥 YouTube":
    st.header("🎥 YouTube")
    q=st.text_input("Search topic:")
    if st.button("Find"):
        vids=youtube_search(q)
        if not vids: st.error("No results or invalid key.")
        for v in vids:
            st.markdown(f"**{v['title']}**")
            st.image(v['thumb'],width=300)
            st.markdown(f"[▶️ Watch on YouTube]({v['url']})")

# --------------- NOTES ---------------
elif menu=="🗒️ Notes":
    st.header("🗒️ Your notes")
    note=st.text_area("Write your note:")
    if st.button("Save Note"):
        with open("notes.txt","a",encoding="utf-8") as f: f.write(note+"\n---\n")
        st.success("Saved!")
    if st.button("View Notes"):
        if os.path.exists("notes.txt"):
            with open("notes.txt","r",encoding="utf-8") as f: st.text_area("Your Notes",f.read(),height=300)
        else: st.info("No notes yet.")

# --------------- VOICE ASSISTANT ---------------
elif menu=="🎧 Voice Assistant":
    st.header("🎧 Talk to your AI Study Buddy")
    file=st.file_uploader("Upload voice (.wav/.mp3):",type=["wav","mp3"])
    if file:
        sound=AudioSegment.from_file(file)
        tmp=tempfile.NamedTemporaryFile(delete=False,suffix=".wav")
        sound.export(tmp.name,format="wav")
        r=sr.Recognizer()
        with sr.AudioFile(tmp.name) as src: audio=r.record(src)
        try:
            q=r.recognize_google(audio)
            st.write(f"🗣 You said: {q}")
            ans=ask_ai(q)
            st.write("🤖",ans)
            st.audio(speak_text(ans))
        except Exception as e: st.error(f"Voice error: {e}")
