"use client";

import { useState, useRef, useEffect } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

export default function AgentChatPanel({ siteId }: { siteId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // Load chat history
    fetch(`${API_URL}/chat/${siteId}/history`)
      .then((r) => r.json())
      .then((data) => {
        if (data.messages?.length > 0) setMessages(data.messages);
      })
      .catch(() => {});
  }, [siteId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage(e?: React.FormEvent) {
    e?.preventDefault();
    if (!input.trim() || loading) return;

    const userMsg: Message = {
      role: "user",
      content: input.trim(),
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${API_URL}/chat/${siteId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg.content }),
      });

      if (!res.ok) throw new Error("Failed to send message");
      const data = await res.json();

      const assistantMsg: Message = {
        role: "assistant",
        content: data.response,
        timestamp: data.timestamp,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Sorry, I encountered an error. Please try again.",
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  async function clearChat() {
    await fetch(`${API_URL}/chat/${siteId}/history`, { method: "DELETE" });
    setMessages([]);
  }

  return (
    <div className="flex flex-col h-[600px] bg-white rounded-xl border border-gray-200 shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
          <h3 className="text-sm font-semibold text-gray-900">SEO Agent</h3>
          <span className="text-xs text-gray-500">Ready to help</span>
        </div>
        <button
          onClick={clearChat}
          className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
        >
          Clear chat
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center mb-3">
              <svg className="w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <p className="text-sm font-medium text-gray-900 mb-1">SERP Strategist Agent</p>
            <p className="text-xs text-gray-500 max-w-xs">
              Ask me to fix SEO issues, generate content, analyze your site, or create reports. I&apos;ll show you exactly what I&apos;ll change and why.
            </p>
            <div className="mt-4 flex flex-wrap gap-2 justify-center">
              {[
                "What are my top SEO issues?",
                "Fix the title tag on the homepage",
                "Generate a meta description for /blog",
                "Show me a site health report",
              ].map((suggestion) => (
                <button
                  key={suggestion}
                  onClick={() => {
                    setInput(suggestion);
                    textareaRef.current?.focus();
                  }}
                  className="text-xs px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-full transition-colors"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${
                msg.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-900"
              }`}
            >
              {msg.role === "assistant" ? (
                <div className="text-sm prose prose-sm max-w-none prose-pre:bg-gray-800 prose-pre:text-gray-100 prose-code:text-blue-700">
                  <FormattedMessage content={msg.content} />
                </div>
              ) : (
                <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-2xl px-4 py-3">
              <div className="flex gap-1">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-gray-200">
        <form onSubmit={sendMessage} className="flex gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask the agent to fix issues, generate content, or analyze your site..."
            className="flex-1 resize-none rounded-xl border border-gray-300 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent max-h-32"
            rows={1}
            disabled={loading}
          />
          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="px-4 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </form>
      </div>
    </div>
  );
}

/**
 * Renders markdown-like content from the agent (code blocks, bold, lists).
 */
function FormattedMessage({ content }: { content: string }) {
  // Split by code blocks
  const parts = content.split(/(```[\s\S]*?```)/g);

  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("```")) {
          // Code block
          const lines = part.slice(3, -3).split("\n");
          const lang = lines[0]?.trim() || "";
          const code = lang ? lines.slice(1).join("\n") : lines.join("\n");

          return (
            <pre key={i} className="rounded-lg overflow-x-auto my-2 p-3 text-xs">
              <code className={lang === "diff" ? "text-xs" : ""}>
                {lang === "diff"
                  ? code.split("\n").map((line, j) => (
                      <span
                        key={j}
                        className={
                          line.startsWith("+")
                            ? "text-green-400 block"
                            : line.startsWith("-")
                            ? "text-red-400 block"
                            : "block"
                        }
                      >
                        {line}
                      </span>
                    ))
                  : code}
              </code>
            </pre>
          );
        }

        // Regular text — handle bold, inline code, bullet points
        return (
          <span key={i}>
            {part.split("\n").map((line, j) => {
              // Bold
              let formatted = line.replace(
                /\*\*(.+?)\*\*/g,
                '<strong>$1</strong>'
              );
              // Inline code
              formatted = formatted.replace(
                /`([^`]+)`/g,
                '<code class="bg-gray-200 px-1 rounded text-xs">$1</code>'
              );
              // Bullet points
              if (line.trim().startsWith("• ") || line.trim().startsWith("- ")) {
                return (
                  <div key={j} className="flex gap-1.5 ml-2">
                    <span>•</span>
                    <span dangerouslySetInnerHTML={{ __html: formatted.replace(/^[\s]*[•-]\s*/, "") }} />
                  </div>
                );
              }
              // Headings (##)
              if (line.trim().startsWith("## ")) {
                return <p key={j} className="font-semibold mt-2 mb-1" dangerouslySetInnerHTML={{ __html: formatted.replace(/^#+\s*/, "") }} />;
              }
              if (line.trim().startsWith("📁") || line.trim().startsWith("🔍")) {
                return <p key={j} className="mt-1" dangerouslySetInnerHTML={{ __html: formatted }} />;
              }

              return line.trim() ? (
                <p key={j} dangerouslySetInnerHTML={{ __html: formatted }} />
              ) : (
                <br key={j} />
              );
            })}
          </span>
        );
      })}
    </>
  );
}
