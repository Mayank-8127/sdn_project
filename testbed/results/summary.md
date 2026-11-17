| scenario | runs | pairs | lost / pair | mean outage | worst outage | controller notified | re-optimisation |
|---|---:|---:|---:|---:|---:|---:|---:|
| link cut (DEN-KSC) | 5 | 30 | 1.6 | 12 ms | 20 ms | 6 ms | 36 ms |
| gray failure, no BFD | 5 | 30 | 181.0 | 1810 ms | 1830 ms | never | never |
| gray failure, OVS BFD 10 ms | 5 | 30 | 4.2 | 42 ms | 60 ms | never | never |
| duct cut (DEN-KSC + SNV-DEN), SRLG not declared | 5 | 60 | 4.7 | 46 ms | 90 ms | 9 ms | 51 ms |
| duct cut (DEN-KSC + SNV-DEN), SRLG declared | 5 | 60 | 2.2 | 20 ms | 40 ms | 8 ms | 52 ms |
