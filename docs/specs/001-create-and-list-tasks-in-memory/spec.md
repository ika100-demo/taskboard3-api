---
spec_id: 001-create-and-list-tasks-in-memory
title: Create and list tasks (in memory)
status: building
priority: P1
shape: service-python
---

# 001 — Create and list tasks (in memory)

## Problem

The Task API exists, but it does not yet handle tasks: it only answers health, readiness and ping. Clients (a future taskboard web app, scripts, testers) cannot record a task or see the tasks recorded so far, so nothing can be built on top of the API. This spec adds the smallest useful core: create a task with a title and an optional due date, and list all tasks. Tasks are kept in the service's memory only. Durable storage comes later.

## Stories

- As an API client, I want to create a task with a title, so that I can record something I need to do.
- As an API client, I want to give a task an optional due date, so that I can record when it must be done.
- As an API client, I want to list all tasks, so that I can show them or act on them.

## Acceptance criteria

- **AC-001.1** Given the service is running, when a client sends `POST /tasks` with JSON `{"title": "Buy milk"}`, then the response is `201` with a JSON task `{"id": <non-empty string>, "title": "Buy milk", "due_date": null}`. (smoke)
- **AC-001.2** Given the service is running, when a client sends `POST /tasks` with `{"title": "File taxes", "due_date": "2026-12-31"}`, then the response is `201` and the returned task has `"due_date": "2026-12-31"` (a calendar date in `YYYY-MM-DD` format, without a time).
- **AC-001.3** Given two tasks were created, when the client compares their `id`s, then the ids differ.
- **AC-001.4** Given no task has been created since the service started, when a client sends `GET /tasks`, then the response is `200` with the JSON array `[]`.
- **AC-001.5** Given tasks A, then B, then C were created, when a client sends `GET /tasks`, then the response is `200` with a JSON array of all three tasks in creation order (A, B, C), each with the same `id`, `title` and `due_date` that its create response returned. (smoke)
- **AC-001.6** Given a create request without `title`, or with a `title` that is empty or only whitespace, when it is sent, then the response is `422` with an error that names the `title` field, and no task is added to the list.
- **AC-001.7** Given a create request whose `title` is longer than 200 characters, when it is sent, then the response is `422` with an error that names the `title` field, and no task is added; a title of exactly 200 characters is accepted.
- **AC-001.8** Given a create request whose `due_date` is not a valid calendar date in `YYYY-MM-DD` format (for example `"2026-02-30"`, `"31.12.2026"` or `"tomorrow"`), when it is sent, then the response is `422` with an error that names the `due_date` field, and no task is added.
- **AC-001.9** Given a create request whose body is not a JSON object, or whose `title` or `due_date` has the wrong JSON type (for example a number), when it is sent, then the response is `422` and no task is added.
- **AC-001.10** Given a create request with `"due_date": null`, when it is sent, then the response is `201` and the task has `"due_date": null`, the same as omitting the field.
- **AC-001.11** Given a title with leading or trailing spaces, such as `"  Buy milk  "`, when the task is created, then the stored and returned title is `"Buy milk"` (whitespace trimmed).
- **AC-001.12** Given the API documentation of the running service, when a client reads it, then `POST /tasks` and `GET /tasks` are listed with their request and response shapes.
- **AC-001.13** Given a create request whose `due_date` is a valid date in the past, such as `"2020-01-15"`, when it is sent, then the response is `201` and the returned task has `"due_date": "2020-01-15"`, unchanged.

## Non-goals

- Keeping tasks across a service restart or redeploy, or sharing them between several running instances. Tasks are lost on restart, and each instance has its own list.
- Reading a single task, updating, completing or deleting tasks.
- Filtering, sorting other than creation order, searching and pagination of the list.
- Users, authentication and per-user task lists.
- Due times or time zones. A due date is a calendar date only.
- Any other task fields (description, priority, status, tags), including a `created_at` timestamp.
- An upper limit on the number of tasks. To be revisited together with persistence.

## Open questions

- ~~Confirm: the title limit is 200 characters.~~ Answered: yes, see AC-001.7.
- ~~Confirm: leading and trailing whitespace in titles is trimmed, and a title that is only whitespace is rejected.~~ Answered: yes, see AC-001.6 and AC-001.11.
- ~~Should a due date in the past be accepted?~~ Answered: yes, accepted unchanged, see AC-001.13.
- ~~Should the list or the number of tasks have an upper limit?~~ Answered: no limit in this spec, revisit with persistence, see Non-goals.
- ~~Confirm: the resource path is `/tasks` and the fields are named `id`, `title` and `due_date`.~~ Answered: yes, as in AC-001.1 to AC-001.13.
- ~~Should a task also carry a `created_at` timestamp in responses?~~ Answered: no, not in this spec, see Non-goals.

## Changelog

- 2026-11-05 created
- 2026-11-05 amended: open questions answered; added AC-001.13 (past due dates accepted unchanged); non-goals now exclude a task-count limit and `created_at`
- 2026-11-05 approved
- 2026-11-05 building
