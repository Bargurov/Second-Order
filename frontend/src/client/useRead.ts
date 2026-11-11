// One GET per key (and per explicit "Read again"): the page's data, a notice, or the end of the session. A reply for a
// key the page has moved past is dropped. Reads never write, quote, run or retry, and none of them is counted.
import { useCallback, useEffect, useState } from "react";
import type { NewsApi } from "../contracts/news.ts";
import type { StoriesApi } from "../contracts/stories.ts";
import type { Reply, UserApi } from "../contracts/user.ts";
import { useClient } from "./context";
import { outcomeOf } from "./controller.ts";
import type { Notice } from "./refusals.ts";

export type ReadState<T> = { state: "loading" } | { state: "ready"; data: T } | { state: "notice"; notice: Notice };

function useReply<T>(read: () => Promise<Reply<T>>, key: string): [ReadState<T>, () => void] {
  const { endSession } = useClient();
  const [shown, setShown] = useState<ReadState<T>>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    setShown({ state: "loading" });
    void read().then((reply) => {
      if (!current) return;
      const outcome = outcomeOf(reply);
      if (outcome.kind === "ok") setShown({ state: "ready", data: outcome.data });
      else if (outcome.kind === "session") endSession(outcome.reason);
      else setShown({ state: "notice", notice: outcome.notice });
    });
    return () => { current = false; };
  }, [key, attempt]);  // `read` is keyed by `key`: a new key is a new read.
  const again = useCallback(() => setAttempt((value) => value + 1), []);
  return [shown, again];
}

/** A read through the user routes (src/contracts/user.ts). */
export function useRead<T>(read: (api: UserApi) => Promise<Reply<T>>, key: string): [ReadState<T>, () => void] {
  const { api } = useClient();
  return useReply(() => read(api), key);
}

/** A read through the news, interests, import and limits routes (src/contracts/news.ts). */
export function useNewsRead<T>(read: (news: NewsApi) => Promise<Reply<T>>, key: string): [ReadState<T>, () => void] {
  const { news } = useClient();
  return useReply(() => read(news), key);
}

/** A read through the stories, topics and Go deeper routes (src/contracts/stories.ts). */
export function useStoriesRead<T>(read: (stories: StoriesApi) => Promise<Reply<T>>,
                                  key: string): [ReadState<T>, () => void] {
  const { stories } = useClient();
  return useReply(() => read(stories), key);
}
