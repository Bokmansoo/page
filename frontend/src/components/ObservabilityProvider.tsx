"use client";

import * as Sentry from "@sentry/nextjs";
import { usePathname } from "next/navigation";
import posthog from "posthog-js";
import { useEffect } from "react";

const sentryDsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
const posthogToken = process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN;
const posthogHost = process.env.NEXT_PUBLIC_POSTHOG_HOST;

let sentryInitialized = false;
let posthogInitialized = false;

function sanitizedPathname(pathname: string): string {
  return pathname
    .replace(/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}/gi, ":id")
    .replace(/\/p\/[^/]+/g, "/p/:id");
}

function redactSentryRequest(event: Sentry.ErrorEvent): Sentry.ErrorEvent {
  if (event.request) {
    delete event.request.cookies;
    delete event.request.data;
    delete event.request.headers;
    delete event.request.query_string;
  }
  delete event.user;
  return event;
}

export function initializeClientObservability() {
  if (sentryDsn && !sentryInitialized) {
    Sentry.init({
      dsn: sentryDsn,
      enabled: true,
      sendDefaultPii: false,
      tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 1,
      beforeSend: redactSentryRequest,
    });
    sentryInitialized = true;
  }

  if (posthogToken && !posthogInitialized) {
    posthog.init(posthogToken, {
      api_host: posthogHost || "https://us.i.posthog.com",
      autocapture: false,
      capture_pageview: false,
      disable_session_recording: true,
      person_profiles: "identified_only",
    });
    posthogInitialized = true;
  }
}

export function ObservabilityProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  useEffect(() => {
    initializeClientObservability();
  }, []);

  useEffect(() => {
    if (posthogInitialized) {
      posthog.capture("sellform_page_viewed", {
        page_path: sanitizedPathname(pathname),
      });
    }
  }, [pathname]);

  return <>{children}</>;
}
