| scenario | runs | pairs | lost / pair | mean outage | worst outage | controller notified | re-optimisation |
|---|---:|---:|---:|---:|---:|---:|---:|
| link cut (DEN-KSC) | 5 | 30 | 1.9 | 14 ms | 30 ms | 8 ms | 29 ms |
| gray failure, no BFD | 5 | 30 | 179.3 | 1793 ms | 1820 ms | never | never |
| gray failure, OVS BFD 10 ms | 5 | 30 | 4.0 | 40 ms | 60 ms | never | never |
| duct cut (DEN-KSC + SNV-DEN), SRLG not declared | 5 | 60 | 3.8 | 38 ms | 60 ms | 7 ms | 47 ms |
| duct cut (DEN-KSC + SNV-DEN), SRLG declared | 5 | 60 | 2.1 | 20 ms | 30 ms | 8 ms | 46 ms |
