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

/** Drop the cached token so the next recognition re-fetches it -- needed
 *  after the user changes their "languages I speak", which ride on the token
 *  response. */
export function resetSpeechToken(): void {
  cached = null;
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

/** A live recognition session started by `startListening()`. Keeps
 *  recognising across natural pauses in speech; call `stop()` when the user
 *  is done talking to finalise the transcript and release the microphone. */
export type ListeningSession = {
  stop: () => Promise<SpeechResult>;
};

/** Start listening from the microphone. Unlike a single "recognize once"
 *  call, this keeps the recognizer open across pauses -- Azure's one-shot
 *  mode ends the whole recognition at the first silence gap, which cut
 *  users off mid-sentence whenever they paused to think. Each completed
 *  phrase is accumulated; call `stop()` to end the session and get the
 *  full transcript back. */
export async function startListening(): Promise<ListeningSession> {
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

  const segments: string[] = [];
  let detectedLocale: string | undefined;
  let cancelDetails: string | null = null;

  recognizer.recognized = (_sender, event) => {
    if (event.result.reason === sdk.ResultReason.RecognizedSpeech && event.result.text) {
      segments.push(event.result.text);
      if (!detectedLocale) {
        const detected = sdk.AutoDetectSourceLanguageResult.fromResult(event.result).language;
        detectedLocale = detected || (languages.length === 1 ? languages[0] : undefined);
      }
    }
  };
  recognizer.canceled = (_sender, event) => {
    cancelDetails = event.errorDetails || String(event.reason);
  };

  try {
    await new Promise<void>((resolve, reject) => {
      recognizer.startContinuousRecognitionAsync(resolve, reject);
    });
  } catch (err) {
    recognizer.close();
    const message = err instanceof Error ? err.message : String(err);
    if (/NotAllowedError|Permission|denied/i.test(message)) {
      throw new SpeechError("Microphone access was denied.", "permission");
    }
    throw new SpeechError(message || "Speech recognition failed.", "failed");
  }

  return {
    stop: () =>
      new Promise<SpeechResult>((resolve, reject) => {
        recognizer.stopContinuousRecognitionAsync(
          () => {
            recognizer.close();
            if (segments.length === 0) {
              if (cancelDetails && /permission|NotAllowedError|microphone/i.test(cancelDetails)) {
                reject(new SpeechError("Microphone access was denied.", "permission"));
              } else {
                reject(new SpeechError("I didn't catch that — try speaking again.", "no_speech"));
              }
              return;
            }
            resolve({ text: segments.join(" "), locale: detectedLocale });
          },
          (err) => {
            recognizer.close();
            reject(new SpeechError(String(err) || "Speech recognition failed.", "failed"));
          }
        );
      }),
  };
}
