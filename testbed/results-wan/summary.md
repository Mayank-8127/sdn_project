| scenario | runs | pairs | probe gap | lost / pair | bursts / pair | mean outage | worst outage | controller notified | re-optimisation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| link cut (DEN-KSC) | 5 | 30 | 9.2 ms | 2.1 | 1.7 | 13 ms | 20 ms | 12 ms | 77 ms |
| gray failure, no BFD | 5 | 30 | 9.4 ms | 198.0 | 1.0 | 1852 ms | 1970 ms | never | never |
| gray failure, OVS BFD 10 ms | 5 | 30 | 8.1 ms | 5.1 | 1.0 | 41 ms | 59 ms | never | never |
| duct cut (DEN-KSC + SNV-DEN), SRLG not declared | 5 | 60 | 9.3 ms | 7.7 | 1.1 | 70 ms | 152 ms | 13 ms | 107 ms |
| duct cut (DEN-KSC + SNV-DEN), SRLG declared | 5 | 60 | 8.9 ms | 3.2 | 1.2 | 27 ms | 56 ms | 14 ms | 104 ms |
