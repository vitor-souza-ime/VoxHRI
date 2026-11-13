# English conversation study protocol — 30 prompts, one session

The application displays one prompt at a time. Press `S` to start recording and say the prompts as shown. Wait until the robot finishes speaking before reading the next one. The session ends automatically after **30 successful answers**, or you may press `F` to finish early (the session is marked **incomplete**). Every API attempt is appended to the session CSV immediately. At finalization, 10 charts are exported to the session's `figures/` folder.

## A. General knowledge (1–5)
1. What is artificial intelligence in one sentence?
2. What is machine learning?
3. How is deep learning different from traditional machine learning?
4. What is the capital of Japan?
5. How many sides does a hexagon have?

## B. Robotics education (6–10)
6. Explain Newton's second law in simple English.
7. Give an everyday example of conservation of energy.
8. What is a sensor in robotics?
9. What is the difference between a motor and a sensor?
10. Explain how a robot uses feedback to correct its movement.

## C. Reasoning and instructions (11–15)
11. If a robot moves two meters forward and one meter backward how far is it from its starting point?
12. A robot travels six meters in three seconds. What is its average speed?
13. If a battery is at eighty percent and drops by twenty percentage points what is its new level?
14. Name three safety checks before activating a mobile robot.
15. Explain how to calibrate a distance sensor in three simple steps.

## D. Conversational memory (16–20)
16. For this fictional test, my name is Alex and my favorite color is green.
17. What name did I tell you to use in this test?
18. Which color did I say I like?
19. In this fictional test I teach a beginner robotics class on Fridays.
20. What day do I teach and what is my favorite color?

## E. Dialogue continuity (21–25)
21. I am designing a beginner robotics lesson about sensors.
22. Suggest a five-minute activity for that lesson.
23. How could I make your activity suitable for students with no programming experience?
24. What materials would I need for that activity?
25. Summarize the lesson plan we just discussed in two sentences.

## F. Natural conversation (26–30)
26. Hello robot. How are you today?
27. Can you suggest a friendly question to start an English conversation?
28. I am nervous about speaking English. What can I practice first?
29. Can you see what is on my desk right now?
30. Thank you for your help. What should I practice tomorrow?

### Research notes

One session of 30 sequential turns provides descriptive evidence, not 30 independent experimental replicates. Keep hardware, microphone, audio level, location, network connection, and temperature fixed where feasible. Speech-recognition errors are logged separately and do not trigger an LLM request. If the LLM request fails, the same question must be repeated. The system retains at most six conversational history pairs. The `transcript_discrepancy` field reflects deviation from the intended script, not a verified ASR error rate. Assess response quality using the separate human-evaluation worksheet rather than claiming automated accuracy measurements.
