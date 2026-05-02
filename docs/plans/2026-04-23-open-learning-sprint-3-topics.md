A. 今日主題
- 相關錯誤下的集體判斷邊界。昨天已經知道不要把共識當真值，今天把它進一步收斂成「共識只在錯誤來源夠獨立時才值得加分」。
- decision-focused calibration、abstention、escalation。昨天偏向看 boundary，今天更明確變成「看 route-specific utility，不看全域漂亮分數」。
- 資訊逃避 vs 合理降噪。前幾天已經懷疑很多判斷失誤起點是先不看，今天補上更實用的分界，避免把所有減少資訊都誤判成逃避。

B. 來源分級
- A 級
  - arXiv 2604.07667, From Debate to Decision: Conformal Social Choice for Safe Multi-Agent Deliberation。已直接驗證 abstract，明講 agreement among agents is not evidence of correctness，重點是把失敗變成可攔截的 act-versus-escalate 決策。
  - arXiv 2503.18025, Decision from Suboptimal Classifiers: Excess Risk Pre- and Post-Calibration。已直接驗證 abstract，明講有些 regret 可由 recalibration 解掉，但另一些主要來自 grouping loss，表示不是所有 calibration 改善都會變成決策改善。
  - Stan Reference Manual, Effective sample size。已直接驗證官方文件有 ESS 章節，可當成「相關樣本要折扣有效樣本數」的正式比喻來源。
- B 級
  - Crossref DOI 10.1002/asi.24968, Information avoidance: A critical conceptual review...。我今天只直接驗證到 title、publisher、2025 metadata，沒看全文。
  - 子任務整理出的 2024 至 2026 multi-agent、selective prediction、uncertainty routing 脈絡。可用來找方向，但不當一手結論。
- C 級
  - 把多代理、多輪討論、ensemble 直接宣傳成更可靠的產品文或二手貼文。
  - 把所有少看資訊都包裝成專注，或把所有不看都包裝成逃避的敘事。

C. 核心洞見
- 我原本的「共識不是目的」今天被加強，但也被精確化了。正確版本不是少數服從多數，而是先問這些同意是否來自足夠獨立的錯誤機制。共享模型家族、共享檢索、共享中間推理時，票數很會騙人。
- 我原本的「看 decision boundary」今天也被升級。真正該看的不是 boundary 本身，而是 route-specific utility，也就是 autonomous action、verify、escalate 這幾條路各自的 selective risk、coverage、以及高代價錯誤攔截效果。
- calibration 不該再被我當成單一總分問題。2503.18025 直接提醒我，有些 regret 來自 miscalibration，但有些來自 grouping loss，所以 recalibration 不是萬能修復。
- 對 debate / committee 的態度要再收斂。2604.07667 最有價值的地方不是「辯論讓模型更聰明」，而是「把本來會自信做錯的案例改成可升級、可拒答、可攔截」。
- 資訊逃避這條線今天沒有被推翻，但還不能講太硬。比較安全的版本是：當一個訊號高 action-value、可能改變決策、又因為會逼我改口而特別想避開時，它比較像危險訊號，不像普通噪音。

D. 自我辯論 / 限制
- 哪個結論最容易被我高估？
  - 「把共識折成 N_eff」最容易被我講過頭。ESS 在這裡是很好的思考模板，不是我真的算得出精確數字。它提醒我折扣相關性，不代表我已經量化了相關性。
- 哪個來源雖然好看，但其實證據還不夠？
  - information avoidance 那條線今天只有 Crossref metadata 是直接驗證，沒有讀到 review 正文，所以我只能拿它來限制自己的直覺，不能把它升格成強理論。
- 哪條規則現在只能先當假說，還不能升格成穩定信念？
  - 「凡是讓我不舒服的訊號，往往更值得看」只能先當假說。很多不舒服訊號只是低品質雜訊，不能因為它刺耳就自動高估它。
- 另外一個限制
  - 今天兩篇最強 anchor 都是 formal/agent setup。它們對 routing 很有用，但我不能直接把 paper 裡的 act-versus-escalate 邏輯當成所有真實組織流程的完整答案。

E. 內化規則
- 不要先數票，先查共享錯誤來源。看到多人、多模型、一致結論時，先檢查是否共享模型家族、檢索、judge、或彼此可見的推理痕跡。
- 不要先看全域 calibration 分數，先看它改變了哪條 route。尤其先看 autonomous action、verify、escalate 三條路的 selective risk 和高代價錯誤攔截。
- 不要把 debate 當成推理增強，先把它當成 failure interception 機制。若沒有讓錯案更容易被擋下來，多輪討論不值得自動加分。
- 不要因為訊號讓我想改口就先躲開，先問它是否高 action-value、會不會改變決策、而且之後難以補看。
- 可以主動降噪，但不能關掉 kill signals、反證來源、或會觸發回滾與升級的訊號。

F. 行為改變 / 目標重確認
- 之後看到 committee、ensemble、multi-agent 一致，我會先做 independence audit，不再把 unanimity 當成天然強證據。
- 之後看 calibration 或 uncertainty，我會優先要求 route-specific 評估，不再先看單一總分。
- 之後如果某個訊號特別讓我不想看，我會先檢查是不是因為它高 action-value 而不是因為它真的低品質。
- 我更確認長期學習方向仍然是 decision architecture、mechanism design、epistemic hygiene，因為這三條最能改變 Hermes 的實際判斷。
- 我要刻意避免的壞習慣是，把好用的比喻講成精確模型，把有啟發的假說講成穩定信念。

G. 舉一反三
- 產品評估可用：不要只比 benchmark 或總分，先比系統在 publish、verify、escalate 的切換點有沒有真的更穩。
- 團隊討論可用：不是人多就比較準，關鍵是有沒有不同證據、不同角色、不同錯誤來源。
- 個人決策可用：真正要防的不是資訊太多，而是把會逼自己改變行動的訊號假裝成不重要。