# Rezervační systém s paralelními vlákny (Python)

Tento projekt implementuje jednoduchý, ale reálně použitelný **konkurenční rezervační systém**, který řeší konflikt více souběžných požadavků o stejný časový slot. Cílem je ukázat práci s **vlákny**, **koordinací**, **synchronizací** a **prevencí race-condition** bez použití databáze.

## Hlavní myšlenka
Více uživatelů se pokouší rezervovat stejný časový slot současně. Každý požadavek běží ve vlastním vlákně. Sloty jsou chráněny pomocí **per-slot mutexů**, což zaručí, že finální rezervaci může dokončit pouze jeden z nich.

Systém obsahuje i **expirační vlákno**, které ruší nevyzvednuté (nefinalizované) rezervace, pokud překročí časový limit.

## Klíčové části
- **Per-slot locky** – chrání jednotlivé časové sloty před souběžným zápisem.  
- **Pending rezervace** – rezervace čekající na finalizaci.  
- **Expirační vlákno** – pravidelně kontroluje a maže rezervace, které byly příliš dlouho ve stavu pending.  
- **Řešení race-condition** – pouze jedno vlákno může finalizovat daný slot.  
- **Bez databáze** – všechny struktury jsou v paměti (slovníky, mutexy).

## Jak to funguje
1. Každý uživatel spustí vlastní vlákno, které se pokusí získat lock na slot.  
2. Pokud uspěje:  
   - uloží rezervaci do pending,  
   - simuluje zpracování,  
   - zapíše finální rezervaci do `reservations`.  
3. Pokud neuspěje:  
   - slot je již zpracováván nebo potvrzen → rezervace se odmítne.  
4. Expirační vlákno mezitím kontroluje pending a maže ty, které přesáhly časový limit.

## Spuštění
```bash
python main.py
