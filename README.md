# Noon Report Checker - Streamlit

Streamlit εφαρμογή για έλεγχο ANTHEA-style Noon Report Excel αρχείων με τους κανόνες validation που προσαρμόστηκαν από το Error Finder v2.25.

## Τι κάνει

- Δέχεται ένα ή πολλά `.xlsx` / `.xlsm` αρχεία.
- Διαβάζει κατά προτεραιότητα sheet `Table`, μετά `Query1`, αλλιώς το πρώτο sheet.
- Εφαρμόζει τους κανόνες validation για Date, Low Steaming, Slip, MCR/ME Load, Electric Load, DG Hours, SFOC, Torque, FW, Sludge, MGO ROB, Reefer Load, Consumption outlier, Distance vs Speed/Time, Boiler και DG consumption.
- Εμφανίζει summary, errors ανά rule και row-by-row checker.
- Εμφανίζει ξεχωριστό πίνακα με τα προβλήματα των τελευταίων 2 report days, ρυθμιζόμενο από το sidebar.
- Περιλαμβάνει KPI dashboard με pies/donut charts, top error categories και daily trend.
- Βγάζει export σε Excel και CSV, μαζί με Recent Errors και Daily KPIs.

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


## Νέα KPIs / views

- **Last N report days**: πίνακας μόνο με τα προβλήματα των τελευταίων N ημερών, με default τις τελευταίες 2 report dates που υπάρχουν στο uploaded αρχείο.
- **Single-day problem table**: επιλογή συγκεκριμένης report date και εμφάνιση μόνο των προβλημάτων εκείνης της ημέρας.
- **Rows OK vs rows with errors**: donut/pie chart για γρήγορη εικόνα ποιότητας.
- **Errors by severity**: High / Medium / Low κατανομή.
- **Top error categories**: bar chart με τους συχνότερους κανόνες που αποτυγχάνουν.
- **Daily validation trend**: daily total errors και rows with errors.

## Σημείωση για columns

Το app περιμένει headers όπως στο `Anthea Y - Noon Report.xlsx`. Υπάρχουν aliases στο `validator.py` για μικρές παραλλαγές ονομάτων. Αν αλλάξει σημαντικά το format, προσθέτεις νέα alias στο `COLUMN_ALIASES`.
