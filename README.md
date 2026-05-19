# Noon Report Checker - Streamlit

Streamlit εφαρμογή για έλεγχο ANTHEA-style Noon Report Excel αρχείων με τους κανόνες validation που προσαρμόστηκαν από το Error Finder v2.25.

## Τι κάνει

- Δέχεται ένα ή πολλά `.xlsx` / `.xlsm` αρχεία.
- Διαβάζει κατά προτεραιότητα sheet `Table`, μετά `Query1`, αλλιώς το πρώτο sheet.
- Εφαρμόζει τους κανόνες validation για Date, Low Steaming, Slip, MCR/ME Load, Electric Load, DG Hours, SFOC, Torque, FW, Sludge, MGO ROB, Reefer Load, Consumption outlier, Distance vs Speed/Time, Boiler και DG consumption.
- Εμφανίζει summary, errors ανά rule και row-by-row checker.
- Βγάζει export σε Excel και CSV.

## Τοπική εκτέλεση

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy στο Streamlit Community Cloud

1. Βάλε τα αρχεία `app.py`, `validator.py`, `requirements.txt` σε GitHub repository.
2. Πήγαινε στο Streamlit Community Cloud.
3. New app → επίλεξε repo/branch → main file `app.py`.
4. Deploy.

## Σημείωση για columns

Το app περιμένει headers όπως στο `Anthea Y - Noon Report.xlsx`. Υπάρχουν aliases στο `validator.py` για μικρές παραλλαγές ονομάτων. Αν αλλάξει σημαντικά το format, προσθέτεις νέα alias στο `COLUMN_ALIASES`.
