| scenario | runs | pairs | probe gap | lost / pair | bursts / pair | mean outage | worst outage | controller notified | re-optimisation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| link cut (DEN-KSC) | 5 | 30 | 9.1 ms | 2.3 | 1.5 | 15 ms | 20 ms | 8 ms | 34 ms |
| gray failure, no BFD | 5 | 30 | 9.4 ms | 198.0 | 1.0 | 1856 ms | 1960 ms | never | never |
| gray failure, OVS BFD 10 ms | 5 | 30 | 8.2 ms | 5.0 | 1.0 | 41 ms | 59 ms | never | never |
| duct cut (DEN-KSC + SNV-DEN), SRLG not declared | 5 | 60 | 9.3 ms | 5.9 | 1.1 | 52 ms | 98 ms | 8 ms | 56 ms |
| duct cut (DEN-KSC + SNV-DEN), SRLG declared | 5 | 60 | 8.8 ms | 3.3 | 1.2 | 26 ms | 49 ms | 10 ms | 63 ms |
