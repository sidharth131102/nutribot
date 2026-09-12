/**
 * Browser-side speech-to-text via the Azure Speech SDK.
 *
 * The subscription key never reaches the browser: we fetch a 10-minute
 * authorization token from the backend (`/api/speech/token`) and recognise
 * one utterance from the default microphone with automatic language
 * detection across the server-configured candidate locales. The transcript
 * and the detected locale go back to the caller; the locale is sent along
 * with the message so the backend translates from the right language.
 *
 * The SDK is loaded lazily so users who never press the mic button don't
 * download it.
 */
import { getSpeechToken, type SpeechTokenResponse } from "./api";

export type SpeechResult = {
  text: string;
  /** BCP-47 locale the recognizer detected, e.g. "hi-IN"; undefined if unknown. */
  locale?: string;
};

export class SpeechError extends Error {
  constructor(message: string, public readonly code: "not_configured" | "permission" | "no_speech" | "failed") {
    super(message);
  }
}

// Refresh a little before the server-declared expiry.
const REFRESH_MARGIN_MS = 30_000;
let cached: { data: SpeechTokenResponse; fetchedAt: number } | null = null;

async function tokenData(): Promise<SpeechTokenResponse> {
  const now = Date.now();
  if (cached && now - cached.fetchedAt < cached.data.expires_in_seconds * 1000 - REFRESH_MARGIN_MS) {
    return cached.data;
  }
  try {
    const data = await getSpeechToken();
    cached = { data, fetchedAt: now };
    return data;
  } catch (err) {
    const message = err instanceof Error ? err.message : "Voice input unavailable";
    throw new SpeechError(message, /not configured/i.test(message) ? "not_configured" : "failed");
  }
}

/** Whether the server has voice input configured (token endpoint reachable). */
export async function isVoiceAvailable(): Promise<boolean> {
  try {
    await tokenData();
    return true;
  } catch {
    return false;
  }
}

/** Recognise a single utterance from the microphone. Resolves when the
 *  speaker pauses; rejects with a SpeechError the UI can explain. */
export async function recognizeOnce(): Promise<SpeechResult> {
  const { token, region, languages } = await tokenData();
  const sdk = await import("microsoft-cognitiveservices-speech-sdk");

  const speechConfig = sdk.SpeechConfig.fromAuthorizationToken(token, region);
  const audioConfig = sdk.AudioConfig.fromDefaultMicrophoneInput();
  const recognizer =
    languages.length > 1
      ? sdk.SpeechRecognizer.FromConfig(
          speechConfig,
          sdk.AutoDetectSourceLanguageConfig.fromLanguages(languages),
          audioConfig
        )
      : (() => {
          if (languages.length === 1) speechConfig.speechRecognitionLanguage = languages[0];
          return new sdk.SpeechRecognizer(speechConfig, audioConfig);
        })();

  try {
    const result = await new Promise<InstanceType<typeof sdk.SpeechRecognitionResult>>((resolve, reject) => {
      recognizer.recognizeOnceAsync(resolve, reject);
    });

    switch (result.reason) {
      case sdk.ResultReason.RecognizedSpeech: {
        const detected = sdk.AutoDetectSourceLanguageResult.fromResult(result).language;
        return { text: result.text, locale: detected || (languages.length === 1 ? languages[0] : undefined) };
      }
      case sdk.ResultReason.NoMatch:
        throw new SpeechError("I didn't catch that — try speaking again.", "no_speech");
      case sdk.ResultReason.Canceled: {
        const details = sdk.CancellationDetails.fromResult(result);
        if (/permission|NotAllowedError|microphone/i.test(details.errorDetails)) {
          throw new SpeechError("Microphone access was denied.", "permission");
        }
        throw new SpeechError(details.errorDetails || "Speech recognition was cancelled.", "failed");
      }
      default:
        throw new SpeechError("Speech recognition failed.", "failed");
    }
  } catch (err) {
    if (err instanceof SpeechError) throw err;
    const message = err instanceof Error ? err.message : String(err);
    if (/NotAllowedError|Permission|denied/i.test(message)) {
      throw new SpeechError("Microphone access was denied.", "permission");
    }
    throw new SpeechError(message || "Speech recognition failed.", "failed");
  } finally {
    recognizer.close();
  }
}
