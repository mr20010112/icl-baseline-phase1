# 冻结协议

将templates/contract.example.yaml复制到contracts/<idea>/v1.yaml并填写。协议校验/冻结：python3 tools/research.py contract validate|freeze --contract contracts/<idea>/v1.yaml。registry记录原始字节；不要改已冻结版本。新版本说明reason/time/seen_results/impact；先前运行保留原协议。
