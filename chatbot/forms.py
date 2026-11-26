from django import forms


class SubirBoletinForm(forms.Form):
    archivo = forms.FileField(label="Excel del boletín (.xlsx)")

    def clean_archivo(self):
        archivo = self.cleaned_data["archivo"]
        if not archivo.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("El archivo debe ser .xlsx")
        return archivo