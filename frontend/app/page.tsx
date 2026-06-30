"use client";

import { useState, useRef, useEffect } from "react";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { AuthGuard } from "@/components/auth-guard";
import { ThemeToggle } from "@/components/theme-toggle";
import { AuthUser, authHeaders, logout } from "@/lib/auth";

// Server API Base URL
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

interface Message {
  role: 'user' | 'ai';
  content: string;
  selected_agent?: string;
  reason?: string;
  sources?: string | null;
  summary?: string | null;
}

export default function Home() {
  return (
    <AuthGuard>
      {(user) => <ChatApp user={user} />}
    </AuthGuard>
  );
}

function ChatApp({ user }: { user: AuthUser }) {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  // Audio & Voice States
  const [isRecording, setIsRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<NodeJS.Timeout | null>(null);
  const audioPlayerRef = useRef<HTMLAudioElement | null>(null);

  // Open expander indices to track UI toggles
  const [openReasoning, setOpenReasoning] = useState<{ [key: number]: boolean }>({});
  const [openSources, setOpenSources] = useState<{ [key: number]: boolean }>({});
  const [openSummary, setOpenSummary] = useState<{ [key: number]: boolean }>({});

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      // Stop all tracks to release mic icon
      mediaRecorderRef.current.stream.getTracks().forEach((track) => track.stop());
      setIsRecording(false);
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading, isRecording]);

  // Recording timer countdown
  useEffect(() => {
    if (isRecording) {
      recordingTimerRef.current = setInterval(() => {
        setRecordingSeconds((prev) => {
          if (prev >= 9) {
            // Auto stop at 10 seconds
            stopRecording();
            return 10;
          }
          return prev + 1;
        });
      }, 1000);
    } else {
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current);
      }
      setRecordingSeconds(0);
    }
    return () => {
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
    };
  }, [isRecording]);

  // Chat message submit
  const sendMessage = async (e?: React.FormEvent, customQuery?: string) => {
    if (e) e.preventDefault();

    const queryText = customQuery ? customQuery.trim() : input.trim();
    if (!queryText || isLoading) return;

    if (!customQuery) setInput("");
    setMessages((prev) => [...prev, { role: "user", content: queryText }]);
    setIsLoading(true);

    // Build chat history as text format
    const chatHistory = messages
      .map((m) => `${m.role === "user" ? "USER" : "ASSISTANT"}: ${m.content}`)
      .join("\n");

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          query: queryText,
          previous_messages: chatHistory
        }),
      });

      if (!res.ok) throw new Error("Server error");
      const data = await res.json();

      const aiMessage: Message = {
        role: "ai",
        content: data.answer || "No response provided by the agent.",
        selected_agent: data.selected_agent,
        reason: data.reason,
        sources: data.sources,
        summary: data.summary
      };

      setMessages((prev) => [...prev, aiMessage]);

      // Automatically play TTS audio if speak mode is requested
      if (customQuery) {
        synthesizeSpeech(aiMessage.content);
      }

    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: "ai", content: "⚠️ Error connecting to the Pership AI service." }
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  // TTS Speech Synthesis
  const synthesizeSpeech = async (text: string) => {
    setIsPlayingAudio(true);
    try {
      const res = await fetch(`${API_BASE}/text-to-speech`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ text }),
      });

      if (res.ok) {
        const audioBlob = await res.blob();
        const audioUrl = URL.createObjectURL(audioBlob);

        if (audioPlayerRef.current) {
          audioPlayerRef.current.src = audioUrl;
          audioPlayerRef.current.play();
        } else {
          const audio = new Audio(audioUrl);
          audioPlayerRef.current = audio;
          audio.play();
        }

        audioPlayerRef.current!.onended = () => {
          setIsPlayingAudio(false);
        };
      }
    } catch (err) {
      console.error("Text-to-speech failed:", err);
      setIsPlayingAudio(false);
    }
  };

  // Browser Audio Recording Functions
  const startRecording = async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert("Audio recording is not supported in this browser.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunksRef.current = [];

      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: "audio/wav" });
        setIsLoading(true);

        const formData = new FormData();
        formData.append("file", audioBlob, "recording.wav");

        try {
          // Transcribe recording
          const transcribeRes = await fetch(`${API_BASE}/audio-transcribe`, {
            method: "POST",
            headers: authHeaders(),
            body: formData,
          });

          if (!transcribeRes.ok) throw new Error("Transcription failed");
          const data = await transcribeRes.json();
          const queryText = data.transcription;

          if (queryText && queryText.trim()) {
            sendMessage(undefined, queryText);
          } else {
            alert("Could not recognize any speech. Please try again.");
            setIsLoading(false);
          }
        } catch (err) {
          console.error("Audio transcription error:", err);
          alert("Error processing voice transcription.");
          setIsLoading(false);
        }
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error("Could not start recording:", err);
      alert("Permission denied or microphone unavailable.");
    }
  };

  const clearChat = () => {
    setMessages([]);
    setOpenReasoning({});
    setOpenSources({});
    setOpenSummary({});
    if (audioPlayerRef.current) {
      audioPlayerRef.current.pause();
      setIsPlayingAudio(false);
    }
  };

  const toggleReasoning = (idx: number) => {
    setOpenReasoning((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const toggleSources = (idx: number) => {
    setOpenSources((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const toggleSummary = (idx: number) => {
    setOpenSummary((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-zinc-950 font-sans text-gray-900 dark:text-gray-100 overflow-hidden">

      {/* MAIN CONTENT AREA: CHAT INTERFACE */}
      <div className="flex-1 flex flex-col h-full relative overflow-hidden">

        {/* Main Header */}
        <header className="flex justify-between items-center px-6 py-4 bg-white dark:bg-zinc-900 shadow-sm border-b-4 border-pership-red flex-shrink-0">
          <div className="flex items-center gap-3">
            {/* Logo */}
            <div className="w-10 h-10 flex items-center justify-center overflow-hidden bg-pership-red/5 dark:bg-white/5 rounded-lg border border-gray-100 dark:border-zinc-800 p-1">
              <img src="/logo.png" alt="Pership" className="w-full h-full object-contain" onError={(e) => {
                // Fallback icon if logo image not found
                e.currentTarget.style.display = 'none';
                e.currentTarget.parentElement!.innerHTML = '<span class="text-xl font-black text-pership-red">P</span>';
              }} />
            </div>
            <div>
              <h1 className="text-xl md:text-2xl font-black tracking-wider text-pership-red dark:text-red-500 uppercase leading-none">Pership AI</h1>
              <p className="text-[9px] font-black tracking-widest text-pership-blue dark:text-blue-400 uppercase leading-none mt-1">Since 1889</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {isPlayingAudio && (
              <div className="flex space-x-1 items-center bg-green-50 dark:bg-green-950/20 text-green-600 px-2.5 py-1 rounded-full text-xs font-semibold border border-green-200 dark:border-green-900/30 animate-pulse">
                <span className="w-2 h-2 bg-green-500 rounded-full"></span>
                <span>Playing Audio</span>
              </div>
            )}

            <ThemeToggle />

            {user.role === "admin" && (
              <Link
                href="/dashboard"
                className="px-3 py-2 text-xs font-bold text-gray-600 dark:text-zinc-300 bg-gray-100 dark:bg-zinc-800 hover:bg-gray-200 dark:hover:bg-zinc-700 hover:text-pership-blue dark:hover:text-blue-400 border border-gray-200 dark:border-zinc-700 rounded-lg transition-colors uppercase tracking-wider flex items-center gap-1.5 shadow-sm"
              >
                ⚙️ Admin
              </Link>
            )}

            <button
              onClick={() => {
                logout();
                router.push("/login");
              }}
              className="px-3 py-2 text-xs font-bold text-gray-600 dark:text-zinc-300 bg-gray-100 dark:bg-zinc-800 hover:bg-gray-200 dark:hover:bg-zinc-700 border border-gray-200 dark:border-zinc-700 rounded-lg transition-colors uppercase tracking-wider shadow-sm"
            >
              Sign Out
            </button>

            <button
              onClick={clearChat}
              disabled={messages.length === 0}
              className="px-4 py-2 text-xs font-bold text-gray-600 dark:text-zinc-300 bg-gray-100 dark:bg-zinc-800 hover:bg-gray-200 dark:hover:bg-zinc-700 hover:text-pership-red dark:hover:text-red-400 border border-gray-200 dark:border-zinc-700 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition-colors uppercase tracking-wider flex items-center gap-1.5 shadow-sm"
            >
              🗑️ Clear Chat
            </button>
          </div>
        </header>

        {/* Chat Conversation Scroll Area */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">

          {/* Welcome Screen */}
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center min-h-[60vh] text-center space-y-4 max-w-2xl mx-auto px-4">
              <div className="flex items-center justify-center w-20 h-20 rounded-full border-[3px] border-pership-red bg-pership-red/5 dark:bg-pership-red/10 mb-2 text-pership-red shadow-sm animate-pulse">
                <span className="text-4xl font-black italic pr-1">P</span>
              </div>
              <h2 className="text-3xl font-extrabold text-pership-blue dark:text-white uppercase tracking-tight">
                Pership AI Assistant
              </h2>
              <p className="text-gray-600 dark:text-zinc-400 text-lg font-medium">
                "With Great Knowledge, Comes Great Power!"
              </p>
              <p className="text-sm font-medium text-gray-400 dark:text-zinc-500 max-w-lg leading-relaxed">
                Seamlessly search internal documents, freight standard operations, Inland Container Terminal policies, dress code guidelines, or leverage general knowledge.
              </p>

              {/* Quick Prompt Cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 w-full pt-4">
                <button
                  onClick={() => sendMessage(undefined, "What is the dress code policy for employees?")}
                  className="p-3 text-left bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl hover:border-pership-red transition text-xs font-semibold text-gray-700 dark:text-zinc-300"
                >
                  👚 Ask Dress Code Guidelines
                </button>
                <button
                  onClick={() => sendMessage(undefined, "What are the finance standard operating procedures?")}
                  className="p-3 text-left bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl hover:border-pership-red transition text-xs font-semibold text-gray-700 dark:text-zinc-300"
                >
                  💵 Check Finance SOPs
                </button>
              </div>
            </div>
          )}

          {/* Conversation Bubbles */}
          <div className="max-w-4xl mx-auto space-y-6 pb-6">
            {messages.map((m, idx) => (
              <div key={idx} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>

                {/* AI Avatar */}
                {m.role === "ai" && (
                  <div className="flex-shrink-0 mr-3 mt-1.5">
                    <div className="w-8 h-8 rounded-full bg-pership-red flex items-center justify-center text-white font-black text-xs shadow-sm">
                      AI
                    </div>
                  </div>
                )}

                <div className="max-w-[85%] md:max-w-[75%] space-y-2">

                  {/* Message Card */}
                  <div className={`p-4 rounded-2xl shadow-sm leading-relaxed border ${m.role === "user"
                    ? "bg-pership-blue text-white border-transparent rounded-br-sm"
                    : "bg-white dark:bg-zinc-900 text-gray-800 dark:text-zinc-200 border-gray-150 dark:border-zinc-800/80 rounded-bl-sm"
                    }`}>

                    {/* Render Text Content */}
                    <div className="whitespace-pre-wrap font-sans text-sm md:text-base">
                      {m.content}
                    </div>

                    {/* Metadata Section (Reasoning, Sources, Summary) */}
                    {m.role === "ai" && (m.selected_agent || m.sources || m.summary) && (
                      <div className="mt-3 pt-3 border-t border-gray-100 dark:border-zinc-800 flex flex-wrap gap-2 text-[10px] font-bold">

                        {/* Reasoning Button */}
                        {m.selected_agent && (
                          <button
                            onClick={() => toggleReasoning(idx)}
                            className={`px-2 py-1 rounded transition flex items-center gap-1 ${openReasoning[idx]
                              ? "bg-pership-red/10 text-pership-red dark:text-red-400"
                              : "bg-gray-100 dark:bg-zinc-800 text-gray-500 dark:text-zinc-400 hover:bg-gray-200"
                              }`}
                          >
                            💡 Routing Reasoning {openReasoning[idx] ? "▲" : "▼"}
                          </button>
                        )}

                        {/* Sources Button */}
                        {m.sources && (
                          <button
                            onClick={() => toggleSources(idx)}
                            className={`px-2 py-1 rounded transition flex items-center gap-1 ${openSources[idx]
                              ? "bg-blue-500/10 text-blue-600 dark:text-blue-400"
                              : "bg-gray-100 dark:bg-zinc-800 text-gray-500 dark:text-zinc-400 hover:bg-gray-200"
                              }`}
                          >
                            📄 Document Sources {openSources[idx] ? "▲" : "▼"}
                          </button>
                        )}

                        {/* Summary Button */}
                        {m.summary && (
                          <button
                            onClick={() => toggleSummary(idx)}
                            className={`px-2 py-1 rounded transition flex items-center gap-1 ${openSummary[idx]
                              ? "bg-purple-500/10 text-purple-600 dark:text-purple-400"
                              : "bg-gray-100 dark:bg-zinc-800 text-gray-500 dark:text-zinc-400 hover:bg-gray-200"
                              }`}
                          >
                            📝 Document Summary {openSummary[idx] ? "▲" : "▼"}
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Collapsible reasoning panel */}
                  {m.role === "ai" && openReasoning[idx] && m.selected_agent && (
                    <div className="p-3 text-xs bg-orange-50/50 dark:bg-amber-950/10 border border-orange-200/50 dark:border-amber-900/20 text-orange-850 dark:text-amber-300 rounded-lg max-w-full">
                      <div className="font-bold uppercase tracking-wider text-[9px] text-orange-600/90 mb-1">
                        Manager Agent Decision:
                      </div>
                      <p className="font-semibold">
                        Routed to: <code className="bg-orange-100 dark:bg-amber-900/30 px-1 py-0.5 rounded font-mono text-[10px]">{m.selected_agent}</code>
                      </p>
                      {m.reason && <p className="mt-1.5 leading-relaxed">{m.reason}</p>}
                    </div>
                  )}

                  {/* Collapsible sources panel */}
                  {m.role === "ai" && openSources[idx] && m.sources && (
                    <div className="p-3 text-xs bg-green-50/40 dark:bg-emerald-950/10 border border-green-200/40 dark:border-emerald-900/20 text-green-800 dark:text-emerald-300 rounded-lg max-w-full">
                      <div className="font-bold uppercase tracking-wider text-[9px] text-green-600 mb-1">
                        Retrieved RAG Sources:
                      </div>
                      <div className="whitespace-pre-wrap font-mono text-[10px] leading-relaxed">
                        {m.sources}
                      </div>
                    </div>
                  )}

                  {/* Collapsible summary panel */}
                  {m.role === "ai" && openSummary[idx] && m.summary && (
                    <div className="p-3 text-xs bg-purple-50/40 dark:bg-purple-950/10 border border-purple-200/40 dark:border-purple-900/20 text-purple-800 dark:text-purple-300 rounded-lg max-w-full">
                      <div className="font-bold uppercase tracking-wider text-[9px] text-purple-600 mb-1">
                        Context Reference Summary:
                      </div>
                      <p className="leading-relaxed font-medium">
                        {m.summary}
                      </p>
                    </div>
                  )}

                </div>
              </div>
            ))}

            {/* Chat loader */}
            {isLoading && (
              <div className="flex justify-start">
                <div className="flex-shrink-0 mr-3 mt-1.5">
                  <div className="w-8 h-8 rounded-full bg-gray-200 dark:bg-zinc-800 animate-pulse flex items-center justify-center text-gray-400 font-bold text-xs">
                    AI
                  </div>
                </div>
                <div className="bg-white dark:bg-zinc-900 p-4 border border-gray-150 dark:border-zinc-800 rounded-2xl rounded-bl-sm shadow-sm flex space-x-2 items-center">
                  <div className="w-2.5 h-2.5 bg-pership-red rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <div className="w-2.5 h-2.5 bg-pership-red rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <div className="w-2.5 h-2.5 bg-pership-red rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            )}

            {/* Pulsing state when microphone is recording */}
            {isRecording && (
              <div className="flex justify-end">
                <div className="bg-pership-red text-white p-4 rounded-2xl rounded-br-sm shadow-lg flex items-center gap-3 border border-red-500/20 animate-pulse">
                  <div className="w-3 h-3 bg-white rounded-full animate-ping"></div>
                  <span className="text-sm font-extrabold uppercase tracking-widest">
                    Recording Audio... ({recordingSeconds}s)
                  </span>
                  <button
                    onClick={stopRecording}
                    className="ml-2 px-3 py-1 bg-white/20 hover:bg-white/30 text-white text-[10px] font-bold uppercase rounded-full transition"
                  >
                    ⏹️ Stop
                  </button>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </main>

        {/* Input Footer Container */}
        <footer className="p-4 bg-white dark:bg-zinc-900 border-t border-gray-200 dark:border-zinc-800 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)] flex-shrink-0">
          <form onSubmit={(e) => sendMessage(e)} className="flex gap-3 max-w-4xl mx-auto">

            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask your Pership Assistant..."
              className="flex-1 p-3 px-5 border border-gray-300 dark:border-zinc-700 rounded-full focus:outline-none focus:ring-2 focus:ring-pership-red focus:border-transparent bg-gray-50 dark:bg-zinc-800 text-gray-900 dark:text-white transition-all shadow-inner font-medium text-sm"
              disabled={isLoading || isRecording}
            />

            {/* Voice Input Button */}
            <button
              type="button"
              onClick={isRecording ? stopRecording : startRecording}
              disabled={isLoading}
              className={`p-3 rounded-full shadow transition-all transform active:scale-95 flex items-center justify-center ${isRecording
                ? "bg-red-500 text-white animate-bounce"
                : "bg-gray-100 hover:bg-gray-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-gray-600 dark:text-zinc-300"
                }`}
              title="Speak to Assistant"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            </button>

            {/* Send Text Button */}
            <button
              type="submit"
              disabled={isLoading || isRecording || !input.trim()}
              className="px-6 py-3 bg-pership-red text-white font-extrabold rounded-full hover:bg-opacity-95 disabled:opacity-50 disabled:cursor-not-allowed transition transform active:scale-95 shadow-md flex items-center justify-center gap-2 text-sm uppercase tracking-wider"
            >
              <span>Send</span>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
            </button>

          </form>
        </footer>

      </div>

    </div>
  );
}
