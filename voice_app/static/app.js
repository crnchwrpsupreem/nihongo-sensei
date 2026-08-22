"use strict";

const elements = {
  safetyPill: document.querySelector("#safety-pill"),
  controllerState: document.querySelector("#controller-state"),
  activeCount: document.querySelector("#active-count"),
  pairCount: document.querySelector("#pair-count"),
  voiceMode: document.querySelector("#voice-mode"),
  startSession: document.querySelector("#start-session"),
  exerciseType: document.querySelector("#exercise-type"),
  turnNumber: document.querySelector("#turn-number"),
  assessment: document.querySelector("#assessment"),
  assessmentRating: document.querySelector("#assessment-rating"),
  assessmentFeedback: document.querySelector("#assessment-feedback"),
  assessmentCorrection: document.querySelector("#assessment-correction"),
  instruction: document.querySelector("#instruction"),
  japaneseContent: document.querySelector("#japanese-content"),
  replay: document.querySelector("#replay"),
  replaySlower: document.querySelector("#replay-slower"),
  answerForm: document.querySelector("#answer-form"),
  answer: document.querySelector("#answer"),
  submitAnswer: document.querySelector("#submit-answer"),
  answerStatus: document.querySelector("#answer-status"),
  microphoneHelp: document.querySelector("#microphone-help"),
  connectMicrophone: document.querySelector("#connect-microphone"),
  disconnectMicrophone: document.querySelector("#disconnect-microphone"),
  autoSubmit: document.querySelector("#auto-submit"),
  connectionState: document.querySelector("#connection-state"),
  toast: document.querySelector("#toast"),
};

let currentPayload = null;
let realtimePeer = null;
let realtimeChannel = null;
let microphoneStream = null;
let submitting = false;
let speechRun = 0;
const transcriptBuffers = new Map();

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body && typeof options.body === "string"
        ? { "Content-Type": "application/json" }
        : {}),
      ...(options.headers || {}),
    },
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    throw new Error(payload.error || payload || `Request failed (${response.status})`);
  }
  return payload;
}

function showError(error) {
  elements.toast.textContent = error.message || String(error);
  elements.toast.classList.remove("hidden");
  window.setTimeout(() => elements.toast.classList.add("hidden"), 7000);
}

function titleForExercise(type) {
  return {
    japanese_to_english: "Japanese → English meaning",
    english_to_japanese: "English → exact Japanese recall",
    contextual_selection: "Choose the exact stored sentence",
    partial_cue_reconstruction: "Reconstruct the exact stored sentence",
  }[type] || "Sentence exercise";
}

function ratingLabel(rating) {
  return {
    correct: "Correct",
    partially_correct: "Partially correct",
    incorrect: "Incorrect",
  }[rating] || rating;
}

function renderPayload(payload) {
  currentPayload = payload;
  const { assessment, exercise, session } = payload;
  elements.controllerState.textContent = session.state.replaceAll("_", " ");
  elements.activeCount.textContent = session.active_card_count;
  elements.pairCount.textContent = session.sentence_pair_count;
  elements.turnNumber.textContent = `Turn ${session.turn + 1}`;
  elements.exerciseType.textContent = titleForExercise(exercise.type);
  elements.instruction.textContent = exercise.instruction_en;

  if (assessment) {
    elements.assessment.classList.remove("hidden");
    elements.assessmentRating.textContent = ratingLabel(assessment.rating);
    elements.assessmentFeedback.textContent = assessment.feedback_en;
    if (assessment.correction_japanese) {
      elements.assessmentCorrection.textContent = assessment.correction_japanese;
      elements.assessmentCorrection.classList.remove("hidden");
    } else {
      elements.assessmentCorrection.textContent = "";
      elements.assessmentCorrection.classList.add("hidden");
    }
  } else {
    elements.assessment.classList.add("hidden");
  }

  elements.japaneseContent.replaceChildren();
  if (exercise.options && exercise.options.length) {
    exercise.options.forEach((option, index) => {
      const row = document.createElement("div");
      row.className = "option";
      const number = document.createElement("span");
      number.className = "option-number";
      number.textContent = `${index + 1}.`;
      const text = document.createElement("span");
      text.className = "japanese";
      text.lang = "ja";
      text.textContent = option;
      row.append(number, text);
      elements.japaneseContent.append(row);
    });
  } else {
    (exercise.japanese_segments || []).forEach((segment) => {
      const text = document.createElement("p");
      text.className = "japanese";
      text.lang = "ja";
      text.textContent = segment;
      elements.japaneseContent.append(text);
    });
  }

  elements.answer.disabled = false;
  elements.submitAnswer.disabled = false;
  elements.replay.disabled = false;
  elements.replaySlower.disabled = false;
  elements.answer.value = "";
  elements.answer.focus();
  speakPayload(payload);
}

function utter(text, language, rate) {
  return new Promise((resolve) => {
    if (!text || !("speechSynthesis" in window)) {
      resolve();
      return;
    }
    const message = new SpeechSynthesisUtterance(text);
    message.lang = language;
    message.rate = rate;
    message.onend = resolve;
    message.onerror = resolve;
    window.speechSynthesis.speak(message);
  });
}

async function speakPayload(payload, japaneseRate = 0.88) {
  if (!("speechSynthesis" in window)) return;
  const run = ++speechRun;
  window.speechSynthesis.cancel();
  setMicrophoneEnabled(false);
  try {
    const assessment = payload.assessment;
    const exercise = payload.exercise;
    if (assessment) {
      await utter(assessment.feedback_en, "en-CA", 1.0);
      if (assessment.correction_japanese) {
        await utter(assessment.correction_japanese, "ja-JP", japaneseRate);
      }
    }
    await utter(exercise.instruction_en, "en-CA", 1.0);
    if (exercise.options && exercise.options.length) {
      for (let index = 0; index < exercise.options.length; index += 1) {
        await utter(`Option ${index + 1}`, "en-CA", 1.0);
        await utter(exercise.options[index], "ja-JP", japaneseRate);
      }
    } else {
      for (const segment of exercise.japanese_segments || []) {
        await utter(segment, "ja-JP", japaneseRate);
      }
    }
  } finally {
    if (run === speechRun) setMicrophoneEnabled(true);
  }
}

function setMicrophoneEnabled(enabled) {
  if (!microphoneStream) return;
  microphoneStream.getAudioTracks().forEach((track) => { track.enabled = enabled; });
}

async function refreshStatus() {
  const status = await api("/api/status");
  elements.safetyPill.textContent = "Local only · Anki read-only";
  elements.controllerState.textContent = status.controller_state.replaceAll("_", " ");
  elements.voiceMode.textContent = status.mode === "realtime-transcription"
    ? "Realtime mic + local speech"
    : "Text/mock + local speech";
  elements.connectMicrophone.disabled = !status.api_key_configured || status.controller_state !== "awaiting_answer";
  elements.microphoneHelp.textContent = status.api_key_configured
    ? `Realtime microphone transcription is available (${status.transcription_model}). Tutor prompts still come only from the local controller.`
    : "Text/mock mode is ready. Set OPENAI_API_KEY before launching to enable Realtime microphone transcription.";
}

async function startSession() {
  elements.startSession.disabled = true;
  elements.startSession.textContent = "Refreshing Anki…";
  try {
    const payload = await api("/api/session/start", {
      method: "POST",
      body: JSON.stringify({}),
    });
    renderPayload(payload);
    elements.connectMicrophone.disabled = !payload.voice.api_key_configured;
    elements.voiceMode.textContent = payload.voice.mode === "realtime-transcription"
      ? "Realtime mic + local speech"
      : "Text/mock + local speech";
  } catch (error) {
    showError(error);
  } finally {
    elements.startSession.disabled = false;
    elements.startSession.textContent = "Refresh session";
  }
}

async function submitAnswer(event) {
  if (event) event.preventDefault();
  const answer = elements.answer.value.trim();
  if (!answer || submitting) return;
  submitting = true;
  elements.submitAnswer.disabled = true;
  elements.answerStatus.textContent = "Assessing locally…";
  try {
    const payload = await api("/api/session/answer", {
      method: "POST",
      body: JSON.stringify({ answer }),
    });
    renderPayload(payload);
  } catch (error) {
    showError(error);
  } finally {
    submitting = false;
    elements.submitAnswer.disabled = false;
    elements.answerStatus.textContent = "";
  }
}

function handleRealtimeEvent(event) {
  let message;
  try {
    message = JSON.parse(event.data);
  } catch {
    return;
  }
  const itemId = message.item_id || message.item?.id || "current";
  if (message.type === "conversation.item.input_audio_transcription.delta") {
    const current = transcriptBuffers.get(itemId) || "";
    transcriptBuffers.set(itemId, current + (message.delta || ""));
    elements.answer.value = transcriptBuffers.get(itemId);
  }
  if (message.type === "conversation.item.input_audio_transcription.completed") {
    const transcript = (message.transcript || transcriptBuffers.get(itemId) || "").trim();
    transcriptBuffers.delete(itemId);
    if (transcript) {
      elements.answer.value = transcript;
      elements.connectionState.textContent = `Transcript ready: ${transcript}`;
      if (elements.autoSubmit.checked && !submitting) submitAnswer();
    }
  }
  if (message.type === "error") {
    showError(new Error(message.error?.message || "Realtime transcription error"));
  }
}

async function connectMicrophone() {
  if (realtimePeer) return;
  elements.connectionState.textContent = "Requesting microphone access…";
  try {
    microphoneStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    realtimePeer = new RTCPeerConnection();
    for (const track of microphoneStream.getTracks()) {
      realtimePeer.addTrack(track, microphoneStream);
    }
    realtimeChannel = realtimePeer.createDataChannel("oai-events");
    realtimeChannel.addEventListener("message", handleRealtimeEvent);
    realtimeChannel.addEventListener("open", () => {
      elements.connectionState.textContent = "Realtime microphone connected. Speak one answer, then pause.";
    });
    const offer = await realtimePeer.createOffer();
    await realtimePeer.setLocalDescription(offer);
    const response = await fetch("/api/realtime/connect", {
      method: "POST",
      headers: { "Content-Type": "application/sdp" },
      body: offer.sdp,
    });
    const answer = await response.text();
    if (!response.ok) {
      let detail = answer;
      try { detail = JSON.parse(answer).error || answer; } catch { /* text response */ }
      throw new Error(detail);
    }
    await realtimePeer.setRemoteDescription({ type: "answer", sdp: answer });
    elements.connectMicrophone.disabled = true;
    elements.disconnectMicrophone.disabled = false;
  } catch (error) {
    disconnectMicrophone();
    showError(error);
  }
}

function disconnectMicrophone() {
  if (realtimeChannel) realtimeChannel.close();
  if (realtimePeer) realtimePeer.close();
  if (microphoneStream) microphoneStream.getTracks().forEach((track) => track.stop());
  realtimeChannel = null;
  realtimePeer = null;
  microphoneStream = null;
  transcriptBuffers.clear();
  elements.disconnectMicrophone.disabled = true;
  refreshStatus().catch(showError);
  elements.connectionState.textContent = "Microphone disconnected.";
}

elements.startSession.addEventListener("click", startSession);
elements.answerForm.addEventListener("submit", submitAnswer);
elements.replay.addEventListener("click", () => currentPayload && speakPayload(currentPayload));
elements.replaySlower.addEventListener("click", () => currentPayload && speakPayload(currentPayload, 0.72));
elements.connectMicrophone.addEventListener("click", connectMicrophone);
elements.disconnectMicrophone.addEventListener("click", disconnectMicrophone);
window.addEventListener("beforeunload", disconnectMicrophone);

refreshStatus().catch(showError);
