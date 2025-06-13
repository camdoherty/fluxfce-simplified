**Your role:**

You are a veteran Python programmer and Linux (XFCE) developer. You possess all skills and knowledge necessary to assist with development and feature requests for the `fluxfce` Python project.


**Goal:** 

Develop a new feature for fluxfce: gradual screen temperature transitions (using xsct)

**Task:**

Thoroughly analyze the `fluxfce` Python project code base, included as a single text file `codebase-2025-06-13`)

You should have a complete understanding of the project and it's goals and function.


**Brainstorm...**

Example of user experience:

During install the user is prompted, eg:
"Enable gradual transitions?"
"duration of transition: <n minutes>"
Then, <n minutes> before sunset, the screen temperature begins to gradually dim until sunset. Same thing occurs for sunrise but in reverse.

The prompts during install populate a variable in config.ini, eg:
"transition_enabled = yes"
"transition_duration = 15"

We'll use systemd similar to how it's already used by fluxfce-sunrise-event.timer and fluxfce-sunset-event.timer (fluxfce-apply-transition@day.service and fluxfce-apply-transition@night.service)

Running `fluxfce enable` will call the new script (let's call it `transition.py`) which schedules dynamic timer for <n minutes> before sunrise and sunset, ie fluxfce-sunrise-event.timer and fluxfce-sunset-event.timer (note that these trigger fluxfce-apply-transition@day.service and fluxfce-apply-transition@night.service respectively)

This new script will flow something like this (very rough):
1. 'get' the current xsct screen temp (we can borrow logic from the `fluxfce set-default --mode day|night` command)
2. check config.ini file for the target temp, eg, if transitioning to night:

```
[ScreenNight]
xsct_temp = 4500
```
3. calculate the difference in screen temp difference pre start of gradual transitst and target (day or night) temp. Example of values required: pre_transition_temp, target_temp, transtion_duration
4. every <n seconds> reduce or increase the temperature so that by the time the target has been reached the temp values are the same
5. exit 

...
---

Okay I'm getting tired. Can you infer my intentions with the above prompt and rewrite it for Gemini. Assume Gemini has the complete code base (I will provide it with your prompt)


